use crate::{Result, err, number, text};
use base64::{Engine, engine::general_purpose::STANDARD};
use neqo_common::{Datagram, Header};
use neqo_http3::{Http3Client, Http3Parameters, Priority};
use neqo_transport::{ConnectionParameters, Output, RandomConnectionIdGenerator, StreamId};
use serde_json::{Value, json};
use std::{
    cell::RefCell,
    collections::{HashMap, VecDeque},
    io,
    net::{SocketAddr, UdpSocket},
    os::fd::{BorrowedFd, FromRawFd, IntoRawFd},
    rc::Rc,
    time::Instant,
};

pub struct Client {
    pub h3: Http3Client,
    pub socket: Option<UdpSocket>,
    pub local: SocketAddr,
    pub remote: SocketAddr,
    pub pending: VecDeque<Datagram>,
    pub sent: u64,
    pub sessions: HashMap<u64, Value>,
}

pub fn decode(value: &Value, name: &str) -> Result<Vec<u8>> {
    STANDARD.decode(text(value, name)?).map_err(err)
}

pub fn headers(value: &Value) -> Result<Vec<Header>> {
    value["headers"]
        .as_array()
        .ok_or("Missing headers")?
        .iter()
        .map(|pair| {
            let name = pair[0].as_str().ok_or("Invalid header name")?;
            let bytes = STANDARD
                .decode(pair[1].as_str().ok_or("Invalid header value")?)
                .map_err(err)?;
            Ok(Header::new(name, bytes))
        })
        .collect()
}

impl Client {
    pub fn new(value: &Value) -> Result<Self> {
        nss::init().map_err(err)?;
        let local = text(value, "local")?.parse().map_err(err)?;
        let remote = text(value, "remote")?.parse().map_err(err)?;
        let parameters = Http3Parameters::default()
            .connection_parameters(ConnectionParameters::default())
            .webtransport(value["webtransport"].as_bool().unwrap_or(false));
        let h3 = Http3Client::new(
            text(value, "host")?,
            Rc::new(RefCell::new(RandomConnectionIdGenerator::new(10))),
            local,
            remote,
            parameters,
            Instant::now(),
        )
        .map_err(err)?;
        // Resumption/0-RTT is deliberately not enabled. Each connection is
        // authenticated by the existing Python trust policy before use.
        Ok(Self {
            h3,
            socket: None,
            local,
            remote,
            pending: VecDeque::new(),
            sent: 0,
            sessions: HashMap::new(),
        })
    }

    pub fn call(&mut self, value: &Value) -> Result<Value> {
        let now = Instant::now();
        match text(value, "op")? {
            "attach" => {
                if self.socket.is_some() {
                    return Err("UDP socket already attached".into());
                }
                let fd = i32::try_from(number(value, "socket")?).map_err(err)?;
                // Clone ownership, never close Python's descriptor. The caller
                // creates a connected nonblocking UDP socket on this thread.
                let owned = unsafe { BorrowedFd::borrow_raw(fd) }
                    .try_clone_to_owned()
                    .map_err(err)?;
                let socket = unsafe { UdpSocket::from_raw_fd(owned.into_raw_fd()) };
                if socket.local_addr().map_err(err)? != self.local
                    || socket.peer_addr().map_err(err)? != self.remote
                {
                    return Err("UDP endpoint mismatch".into());
                }
                socket.set_nonblocking(true).map_err(err)?;
                self.socket = Some(socket);
                Ok(json!({}))
            }
            "pump" => self.pump(),
            "events" => self.events(),
            "auth" => {
                let accepted = value["accepted"].as_bool().ok_or("Missing auth result")?;
                self.h3.authenticated(
                    if accepted {
                        nss::AuthenticationStatus::Ok
                    } else {
                        nss::AuthenticationStatus::CertUntrusted
                    },
                    now,
                );
                Ok(json!({}))
            }
            "info" => Ok(json!({"tls": self.h3.tls_info().map(|info| json!({
                "version": "TLSv1.3", "backend": "NSS", "nss": "3.130", "nspr": "4.40", "alpn": info.alpn(), "cipher_suite": info.cipher_suite(),
                "resumed": info.resumed(), "profile": "ruyijs-macos-neqo-defaults"})),
                "certificates": self.certificates()})),
            "fetch" => {
                let fields = headers(value)?;
                let urgency = value["urgency"].as_u64().unwrap_or(4).min(7) as u8;
                let id = self
                    .h3
                    .fetch(
                        now,
                        text(value, "method")?,
                        ("https", text(value, "authority")?, text(value, "path")?),
                        &fields,
                        Priority::new(urgency, value["incremental"].as_bool().unwrap_or(false)),
                    )
                    .map_err(err)?;
                Ok(json!({"stream": id.as_u64()}))
            }
            "read" => {
                let size = number(value, "size")?;
                if size == 0 || size > 65536 {
                    return Err("Read size must be 1..65536".into());
                }
                let mut data = vec![0; size as usize];
                let (count, fin) = self
                    .h3
                    .read_data(now, StreamId::new(number(value, "stream")?), &mut data)
                    .map_err(err)?;
                Ok(json!({"data": STANDARD.encode(&data[..count]), "fin": fin}))
            }
            "write" => {
                let data = decode(value, "data")?;
                if data.len() > 65536 {
                    return Err("Write exceeds 64 KiB".into());
                }
                let count = self
                    .h3
                    .send_data(StreamId::new(number(value, "stream")?), &data, now)
                    .map_err(err)?;
                Ok(json!({"count": count}))
            }
            "finish" => {
                self.h3
                    .stream_close_send(StreamId::new(number(value, "stream")?), now)
                    .map_err(err)?;
                Ok(json!({}))
            }
            "cancel" => {
                self.h3
                    .cancel_fetch(StreamId::new(number(value, "stream")?), 0x10c)
                    .map_err(err)?;
                Ok(json!({}))
            }
            "webtransport" => self.webtransport(value),
            operation => Err(format!("Unknown QUIC operation: {operation}")),
        }
    }

    pub fn certificates(&self) -> Vec<String> {
        self.h3
            .peer_certificate()
            .map(|chain| chain.iter().map(|der| STANDARD.encode(der)).collect())
            .unwrap_or_default()
    }

    pub fn pump(&mut self) -> Result<Value> {
        let socket = self.socket.as_ref().ok_or("Missing UDP socket")?;
        let mut data = [0; 65536];
        // Bound work per call so command cancellation cannot be starved by UDP.
        for _ in 0..256 {
            match socket.recv(&mut data) {
                Ok(0) => continue,
                Ok(count) => self.h3.process_input(
                    Datagram::new(
                        self.remote,
                        self.local,
                        Default::default(),
                        data[..count].to_vec(),
                    ),
                    Instant::now(),
                ),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(err(e)),
            }
        }
        for _ in 0..256 {
            if let Some(datagram) = self.pending.front() {
                match socket.send(datagram) {
                    Ok(count) if count == datagram.len() => {
                        self.sent += count as u64;
                        self.pending.pop_front();
                    }
                    Ok(_) => return Err("Partial UDP send".into()),
                    Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                        return Ok(json!({"delay": 0.001}));
                    }
                    Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                    Err(e) => return Err(err(e)),
                }
            }
            match self.h3.process_output(Instant::now()) {
                Output::Datagram(packet) => self.pending.push_back(packet),
                Output::Callback(delay) => return Ok(json!({"delay": delay.as_secs_f64()})),
                Output::None => return Ok(json!({"delay": 0.1})),
            }
        }
        Ok(json!({"delay": 0.0}))
    }

    pub fn close(&mut self) {
        self.h3.close(Instant::now(), 0x100, "closed");
        let _ = self.pump();
    }
}
