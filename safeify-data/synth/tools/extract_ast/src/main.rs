//! .rs -> .ast (syn `{:#?}` Debug dump), identical to SafeNet's rust_ast extractor.
//! Usage: extract_ast <in_dir> <out_dir>

use std::fs;
use std::io::Write;
use std::path::Path;

fn walk(dir: &Path, in_root: &Path, out_root: &Path, ok: &mut u32, err: &mut u32) {
    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("skip dir {:?}: {}", dir, e);
            return;
        }
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            walk(&path, in_root, out_root, ok, err);
            continue;
        }
        let name = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n,
            None => continue,
        };
        if !name.ends_with(".rs") {
            continue;
        }
        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("read {:?}: {}", path, e);
                *err += 1;
                continue;
            }
        };
        let ast = match syn::parse_file(&content) {
            Ok(a) => a,
            Err(e) => {
                eprintln!("parse {:?}: {}", path, e);
                *err += 1;
                continue;
            }
        };
        let rel = path.strip_prefix(in_root).unwrap_or(&path);
        let mut out_path = out_root.join(rel);
        out_path.set_extension("ast");
        if let Some(parent) = out_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let mut f = match fs::File::create(&out_path) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("create {:?}: {}", out_path, e);
                *err += 1;
                continue;
            }
        };
        if f.write_all(format!("{:#?}", ast).as_bytes()).is_err() {
            *err += 1;
            continue;
        }
        *ok += 1;
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: extract_ast <in_dir> <out_dir>");
        std::process::exit(2);
    }
    let in_dir = Path::new(&args[1]);
    let out_dir = Path::new(&args[2]);
    if !in_dir.is_dir() {
        eprintln!("not a directory: {:?}", in_dir);
        std::process::exit(2);
    }
    let (mut ok, mut err) = (0u32, 0u32);
    walk(in_dir, in_dir, out_dir, &mut ok, &mut err);
    println!("extracted={} failed={}", ok, err);
    if err > 0 {
        std::process::exit(1);
    }
}
