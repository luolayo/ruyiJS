use crate::{
    Result,
    client::{Client, decode, headers},
    err, number, text,
};
use base64::{Engine, engine::general_purpose::STANDARD};
use neqo_http3::{SendGroupId, webtransport::ClientSession};
use neqo_transport::{StreamId, StreamType};
use serde_json::{Value, json};
use std::time::Instant;

impl Client {
    pub fn session_info(&mut self, id: StreamId) -> Result<Value> {
        if !self.sessions.contains_key(&id.as_u64()) {
            return Err("Unknown WebTransport session".into());
        }
        let mut result = self.sessions[&id.as_u64()].clone();
        if let Ok(size) = self.h3.webtransport_max_datagram_size(id) {
            result["maxDatagramSize"] = json!(size);
        }
        if let Ok(protocol) = self.h3.webtransport_session_protocol(id) {
            result["protocol"] = json!(protocol);
        }
        if let Ok(stats) = self.h3.webtransport_session_stats(id) {
            result["expiredOutgoing"] = json!(stats.datagrams_expired_outgoing);
        }
        let stats = self.h3.transport_stats();
        // Each Session uses a dedicated connection; these are Neqo's counters.
        for (name, value) in [
            ("bytesSent", json!(self.sent)),
            ("bytesReceived", json!(stats.bytes_rx)),
            ("packetsSent", json!(stats.packets_tx)),
            ("packetsReceived", json!(stats.packets_rx)),
            ("bytesLost", json!(stats.bytes_lost)),
            ("packetsLost", json!(stats.lost)),
            ("bytesAcknowledged", json!(stats.bytes_acked)),
            ("smoothedRtt", json!(stats.rtt.as_secs_f64() * 1000.0)),
            ("rttVariation", json!(stats.rttvar.as_secs_f64() * 1000.0)),
            ("minRtt", json!(stats.min_rtt.as_secs_f64() * 1000.0)),
            ("lostOutgoing", json!(stats.datagram_tx.lost)),
        ] {
            result[name] = value;
        }
        self.sessions.insert(id.as_u64(), result.clone());
        Ok(result)
    }

    pub fn webtransport(&mut self, value: &Value) -> Result<Value> {
        let now = Instant::now();
        let id = || number(value, "session").map(StreamId::new);
        let stream = || number(value, "stream").map(StreamId::new);
        match text(value, "action")? {
            "open" => {
                let fields = headers(value)?;
                let session = self
                    .h3
                    .webtransport_create_session(
                        now,
                        ("https", text(value, "authority")?, text(value, "path")?),
                        &fields,
                    )
                    .map_err(err)?;
                self.sessions
                    .insert(session.as_u64(), json!({"maxDatagramSize": 0}));
                Ok(json!({"session": session.as_u64()}))
            }
            "info" => self.session_info(id()?),
            "stream" => {
                let group = value["group"].as_u64().map(SendGroupId::new);
                let kind = if value["bidirectional"]
                    .as_bool()
                    .ok_or("Missing stream direction")?
                {
                    StreamType::BiDi
                } else {
                    StreamType::UniDi
                };
                let stream = self
                    .h3
                    .webtransport_create_stream_with_send_group(id()?, kind, group)
                    .map_err(err)?;
                self.h3
                    .webtransport_set_sendorder(stream, value["order"].as_i64())
                    .map_err(err)?;
                Ok(json!({"stream": stream.as_u64()}))
            }
            "datagram" => {
                self.h3
                    .webtransport_send_datagram(id()?, &decode(value, "data")?, None, now)
                    .map_err(err)?;
                Ok(json!({}))
            }
            "close" => {
                self.session_info(id()?)?;
                self.h3
                    .webtransport_close_session(
                        id()?,
                        u32::try_from(number(value, "code")?).map_err(err)?,
                        text(value, "reason")?,
                        now,
                    )
                    .map_err(err)?;
                Ok(json!({}))
            }
            "group" => Ok(
                json!({"group": self.h3.webtransport_create_send_group(id()?).map_err(err)?.as_u64()}),
            ),
            "set_group" => {
                if let Some(group) = value["group"].as_u64() {
                    let group = SendGroupId::new(group);
                    if !self
                        .h3
                        .webtransport_validate_send_group(id()?, group)
                        .map_err(err)?
                    {
                        return Err("Send group belongs to another session".into());
                    }
                    self.h3
                        .webtransport_set_sendgroup(stream()?, group)
                        .map_err(err)?;
                } else {
                    self.h3
                        .webtransport_clear_sendgroup(stream()?)
                        .map_err(err)?;
                }
                Ok(json!({}))
            }
            "order" => {
                self.h3
                    .webtransport_set_sendorder(stream()?, value["order"].as_i64())
                    .map_err(err)?;
                Ok(json!({}))
            }
            "stream_stats" => {
                if value["sending"]
                    .as_bool()
                    .ok_or("Missing stats direction")?
                {
                    let stats = self
                        .h3
                        .webtransport_send_stream_stats(stream()?)
                        .map_err(err)?;
                    Ok(
                        json!({"bytesWritten": stats.written, "bytesSent": stats.sent, "bytesAcknowledged": stats.acked}),
                    )
                } else {
                    let stats = self
                        .h3
                        .webtransport_recv_stream_stats(stream()?)
                        .map_err(err)?;
                    Ok(
                        json!({"bytesReceived": stats.bytes_received, "bytesRead": stats.bytes_read}),
                    )
                }
            }
            "reset" | "stop" => {
                let code = number(value, "code")?;
                // WebTransport application errors occupy a reserved HTTP/3 range.
                let code = 0x52e4a40fa8db + code + code / 0x1e;
                if text(value, "action")? == "reset" {
                    self.h3.stream_reset_send(stream()?, code).map_err(err)?;
                } else {
                    self.h3.stream_stop_sending(stream()?, code).map_err(err)?;
                }
                Ok(json!({}))
            }
            "export" => {
                let mut data = [0; 32];
                self.h3
                    .webtransport_export_keying_material(
                        id()?,
                        &decode(value, "label")?,
                        &decode(value, "context")?,
                        &mut data,
                    )
                    .map_err(err)?;
                Ok(json!({"data": STANDARD.encode(data)}))
            }
            action => Err(format!("Unknown WebTransport action: {action}")),
        }
    }
}
