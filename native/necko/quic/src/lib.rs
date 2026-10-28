//! JSON/ctypes boundary for the existing Necko HTTP/3 protocol thread.
use serde_json::{Value, json};
use std::{
    cell::RefCell,
    collections::HashMap,
    ffi::{CString, c_char, c_void},
    sync::atomic::{AtomicU64, Ordering},
};

mod client;
mod events;
mod webtransport;

type Result<T> = std::result::Result<T, String>;
fn err(error: impl std::fmt::Debug) -> String {
    format!("{error:?}")
}
fn text<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    value[name]
        .as_str()
        .ok_or_else(|| format!("Missing string: {name}"))
}
fn number(value: &Value, name: &str) -> Result<u64> {
    value[name]
        .as_u64()
        .ok_or_else(|| format!("Missing unsigned integer: {name}"))
}

// Neqo owns Rc values and must remain on the Python connection's protocol thread.
// Globally unique handles also reject accidental calls from a different thread.
thread_local! {
    static CONNECTIONS: RefCell<HashMap<u64, client::Client>> = RefCell::new(HashMap::new());
    static REPLY: RefCell<CString> = RefCell::new(CString::default());
}
static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);

fn dispatch(handle: u64, value: Value) -> Result<Value> {
    CONNECTIONS.with_borrow_mut(|connections| match text(&value, "op")? {
        "new" => {
            let connection = client::Client::new(&value)?;
            let id = NEXT_HANDLE.fetch_add(1, Ordering::Relaxed);
            connections.insert(id, connection);
            Ok(json!({"handle": id}))
        }
        "close" => {
            if let Some(mut connection) = connections.remove(&handle) {
                connection.close();
            }
            Ok(json!({}))
        }
        _ => connections
            .get_mut(&handle)
            .ok_or("Unknown QUIC handle or wrong protocol thread")?
            .call(&value),
    })
}

/// Input is borrowed for this call; output lives until this thread's next call.
/// The Python protocol bounds frames at 2 MiB. Panics never cross the C ABI.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn necko_quic_call(
    handle: u64,
    data: *const c_char,
    length: usize,
) -> *const c_char {
    let result = std::panic::catch_unwind(|| {
        if data.is_null() || length > 2 * 1024 * 1024 {
            return Err("Invalid QUIC command buffer".into());
        }
        let bytes = unsafe { std::slice::from_raw_parts(data.cast::<u8>(), length) };
        dispatch(handle, serde_json::from_slice(bytes).map_err(err)?)
    })
    .unwrap_or_else(|_| Err("Neqo bridge panicked".into()));
    REPLY.with_borrow_mut(|reply| {
        *reply = CString::new(
            result
                .unwrap_or_else(|error| json!({"error": error}))
                .to_string(),
        )
        .unwrap();
        reply.as_ptr()
    })
}

// Kept for ABI compatibility. Certificate compression is not advertised by this
// build, so no Python decoder callback is retained or called by NSS.
#[unsafe(no_mangle)]
pub extern "C" fn necko_quic_set_decoder(_decoder: *const c_void) {}
