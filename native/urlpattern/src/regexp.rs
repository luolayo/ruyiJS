use crate::RyStr;
use std::ffi::c_void;
use urlpattern::{regexp::RegExp, RegexSyntax};

extern "C" {
    fn ruyijs_urlpattern_regexp_valid(pattern: *const u16, len: usize, ignore: bool) -> bool;
    fn ruyijs_urlpattern_regexp_exec(pattern: *const u16, len: usize, ignore: bool,
        text: *const u8, text_len: usize, match_only: bool, matched: *mut bool, captures: *mut c_void) -> bool;
}

#[derive(Debug)]
pub struct JsRegExp {
    pattern: String,
    units: Vec<u16>,
    ignore_case: bool,
}

impl RegExp for JsRegExp {
    fn syntax() -> RegexSyntax { RegexSyntax::EcmaScript }
    fn parse(pattern: &str, flags: &str, _force_eval: bool) -> Result<Self, ()> {
        let units: Vec<u16> = pattern.encode_utf16().collect();
        let ignore_case = flags.contains('i');
        if !unsafe { ruyijs_urlpattern_regexp_valid(units.as_ptr(), units.len(), ignore_case) } {
            return Err(());
        }
        Ok(Self { pattern: pattern.to_owned(), units, ignore_case })
    }
    fn pattern_string(&self) -> &str { &self.pattern }
    fn matches<'a>(&self, text: &'a str) -> Option<Vec<Option<&'a str>>> {
        let mut captures: Vec<Option<String>> = Vec::new();
        let mut matched = false;
        let ok = unsafe { ruyijs_urlpattern_regexp_exec(self.units.as_ptr(), self.units.len(),
            self.ignore_case, text.as_ptr(), text.len(), false, &mut matched,
            &mut captures as *mut _ as *mut c_void) };
        if !ok || !matched { return None; }
        let mut result = Vec::with_capacity(captures.len());
        for capture in captures {
            result.push(match capture {
                None => None,
                Some(value) => {
                    let start = text.find(&value)?;
                    Some(&text[start..start + value.len()])
                }
            });
        }
        Some(result)
    }
}

#[no_mangle]
pub unsafe extern "C" fn ruyijs_urlpattern_push_capture(captures: *mut c_void, value: RyStr) {
    let output = &mut *(captures as *mut Vec<Option<String>>);
    output.push(value.text().map(str::to_owned));
}
