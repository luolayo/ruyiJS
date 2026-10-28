mod regexp;
use regexp::JsRegExp;
use std::{borrow::Cow, ffi::c_void, ptr};
use urlpattern::{component::Component, quirks, regexp::RegExp, RegexSyntax, UrlPattern, UrlPatternOptions};

#[repr(C)]
#[derive(Clone, Copy)]
pub struct RyStr { data: *const u8, len: usize, valid: bool }
impl RyStr {
    unsafe fn text<'a>(self) -> Option<&'a str> {
        if !self.valid { return None; }
        if self.len == 0 { return Some(""); }
        if self.data.is_null() { return None; }
        std::str::from_utf8(std::slice::from_raw_parts(self.data, self.len)).ok()
    }
    fn of(text: &str) -> Self { Self { data: text.as_ptr(), len: text.len(), valid: true } }
}
#[repr(C)]
pub struct RyInit { fields: [RyStr; 9] }
unsafe fn init(input: *const RyInit) -> quirks::UrlPatternInit {
    let f = &(*input).fields;
    quirks::UrlPatternInit { protocol: f[0].text().map(str::to_owned), username: f[1].text().map(str::to_owned),
        password: f[2].text().map(str::to_owned), hostname: f[3].text().map(str::to_owned),
        port: f[4].text().map(str::to_owned), pathname: f[5].text().map(str::to_owned),
        search: f[6].text().map(str::to_owned), hash: f[7].text().map(str::to_owned),
        base_url: f[8].text().map(str::to_owned) }
}
fn construct(input: quirks::StringOrInit, base: Option<&str>, ignore_case: bool) -> *mut c_void {
    let Ok(input) = quirks::process_construct_pattern_input(input, base) else { return ptr::null_mut(); };
    let options = UrlPatternOptions { ignore_case, regex_syntax: RegexSyntax::EcmaScript };
    match UrlPattern::<JsRegExp>::parse(input, options) {
        Ok(pattern) => Box::into_raw(Box::new(pattern)) as *mut c_void,
        Err(_) => ptr::null_mut(),
    }
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_parse_string(input: RyStr, base: RyStr, ignore: bool) -> *mut c_void {
    let Some(text) = input.text() else { return ptr::null_mut(); };
    construct(quirks::StringOrInit::String(Cow::Borrowed(text)), base.text(), ignore)
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_parse_init(input: *const RyInit, ignore: bool) -> *mut c_void {
    construct(quirks::StringOrInit::Init(init(input)), None, ignore)
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_free(pattern: *mut c_void) {
    if !pattern.is_null() { drop(Box::from_raw(pattern as *mut UrlPattern<JsRegExp>)); }
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_has_regexp_groups(pattern: *const c_void) -> bool {
    (*(pattern as *const UrlPattern<JsRegExp>)).has_regexp_groups()
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_component(pattern: *const c_void, index: u32) -> *const c_void {
    let p = &*(pattern as *const UrlPattern<JsRegExp>);
    let components = [&p.protocol, &p.username, &p.password, &p.hostname, &p.port, &p.pathname, &p.search, &p.hash];
    components[index as usize] as *const Component<JsRegExp> as *const c_void
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_component_pattern(component: *const c_void) -> RyStr {
    RyStr::of(&(*(component as *const Component<JsRegExp>)).pattern_string)
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_component_regexp_empty(component: *const c_void) -> bool {
    (*(component as *const Component<JsRegExp>)).regexp.as_ref().map(|r| r.pattern_string().is_empty()).unwrap_or(true)
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_component_group_count(component: *const c_void) -> usize {
    (*(component as *const Component<JsRegExp>)).group_name_list.len()
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_component_group_name(component: *const c_void, index: usize) -> RyStr {
    let component = &*(component as *const Component<JsRegExp>);
    RyStr::of(&component.group_name_list[index])
}
extern "C" { fn ruyijs_urlpattern_sink(sink: *mut c_void, value: RyStr); }
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_component_matches(component: *const c_void, text: RyStr,
    match_only: bool, sink: *mut c_void) -> bool {
    let Some(text) = text.text() else { return false; };
    let Some(captures) = (*(component as *const Component<JsRegExp>)).matcher.matches(text) else { return false; };
    if !match_only {
        for capture in captures {
            ruyijs_urlpattern_sink(sink, capture.map(RyStr::of).unwrap_or(RyStr { data: ptr::null(), len: 0, valid: false }));
        }
    }
    true
}
unsafe fn match_input(input: quirks::StringOrInit, base: Option<&str>, sink: *mut c_void) -> bool {
    let Ok(Some((input, _))) = quirks::process_match_input(input, base) else { return false; };
    let Some(input) = quirks::parse_match_input(input) else { return false; };
    for value in [&input.protocol, &input.username, &input.password, &input.hostname, &input.port,
                  &input.pathname, &input.search, &input.hash] { ruyijs_urlpattern_sink(sink, RyStr::of(value)); }
    true
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_match_input_string(input: RyStr, base: RyStr, sink: *mut c_void) -> bool {
    let Some(text) = input.text() else { return false; };
    match_input(quirks::StringOrInit::String(Cow::Borrowed(text)), base.text(), sink)
}
#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_match_input_init(input: *const RyInit, sink: *mut c_void) -> bool {
    match_input(quirks::StringOrInit::Init(init(input)), None, sink)
}
