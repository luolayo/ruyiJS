use crate::{Result, client::Client};
use base64::{Engine, engine::general_purpose::STANDARD};
use neqo_common::event::Provider;
use neqo_http3::{Http3ClientEvent as Event, Http3State, WebTransportEvent as Wt};
use serde_json::{Value, json};

impl Client {
    pub fn events(&mut self) -> Result<Value> {
        let mut events = Vec::new();
        for _ in 0..256 {
            let Some(event) = self.h3.next_event() else {
                break;
            };
            let value = match event {
                Event::AuthenticationNeeded => {
                    json!({"type": "auth", "certificates": self.certificates()})
                }
                Event::EchFallbackAuthenticationNeeded { .. } => json!({"type": "ech_retry"}),
                Event::StateChange(Http3State::Connected) => {
                    json!({"type": "state", "state": "connected"})
                }
                Event::GoawayReceived => {
                    let last = match self.h3.state() {
                        Http3State::GoingAway(last) => last.as_u64(),
                        _ => continue,
                    };
                    json!({"type": "state", "state": "going_away", "last": last})
                }
                Event::StateChange(Http3State::GoingAway(last)) => {
                    json!({"type": "state", "state": "going_away", "last": last.as_u64()})
                }
                Event::StateChange(Http3State::Closed(reason) | Http3State::Closing(reason)) => {
                    json!({"type": "state", "state": "closed", "reason": format!("{reason:?}")})
                }
                Event::HeaderReady {
                    stream_id,
                    headers,
                    interim,
                    fin,
                } => {
                    json!({"type": "headers", "stream": stream_id.as_u64(), "interim": interim, "fin": fin,
                    "headers": headers.iter().map(|header| (header.name(), STANDARD.encode(header.value()))).collect::<Vec<_>>()})
                }
                Event::DataReadable { stream_id } => {
                    json!({"type": "readable", "stream": stream_id.as_u64()})
                }
                Event::Reset {
                    stream_id, error, ..
                } => json!({"type": "reset", "stream": stream_id.as_u64(), "error": error}),
                Event::StopSending { stream_id, error } => {
                    json!({"type": "stop_sending", "stream": stream_id.as_u64(), "error": error})
                }
                Event::WebTransport(event) => match event {
                    Wt::Negotiated(available) => {
                        json!({"type": "wt_negotiated", "available": available})
                    }
                    Wt::NewSession {
                        stream_id, status, ..
                    } => {
                        json!({"type": "wt_session", "session": stream_id.as_u64(), "status": status})
                    }
                    Wt::NewStream {
                        stream_id,
                        session_id,
                    } => {
                        json!({"type": "wt_stream", "session": session_id.as_u64(), "stream": stream_id.as_u64(), "bidirectional": !stream_id.is_uni()})
                    }
                    Wt::Datagram {
                        session_id,
                        datagram,
                    } => {
                        json!({"type": "wt_datagram", "session": session_id.as_u64(), "data": STANDARD.encode(datagram)})
                    }
                    Wt::Draining { stream_id } => {
                        json!({"type": "wt_draining", "session": stream_id.as_u64()})
                    }
                    Wt::SessionClosed {
                        stream_id, reason, ..
                    } => {
                        use neqo_http3::features::extended_connect::session::CloseReason;
                        let (clean, code, message) = match reason {
                            CloseReason::Clean { error, message } => {
                                (true, u64::from(error), message)
                            }
                            CloseReason::Error(code) => {
                                (false, code, format!("WebTransport error {code}"))
                            }
                            CloseReason::Status(status) => {
                                (false, 0, format!("WebTransport HTTP {status}"))
                            }
                        };
                        json!({"type": "wt_closed", "session": stream_id.as_u64(), "clean": clean, "code": code, "reason": message})
                    }
                },
                _ => continue,
            };
            events.push(value);
        }
        Ok(json!({"events": events, "more": self.h3.has_events()}))
    }
}
