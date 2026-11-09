//! dsd desktop shell: starts the bundled backend (`dsd ui`) on a free localhost port, shows a splash
//! until it answers, then points the window at it. The backend is stopped when the app quits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

fn free_port() -> u16 {
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

/// Bundled backend inside the .app; `DSD_BACKEND` overrides; falls back to the local PyInstaller build in dev.
fn backend_path(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(p) = std::env::var("DSD_BACKEND") {
        return PathBuf::from(p);
    }
    if let Ok(dir) = app.path().resource_dir() {
        let p = dir.join("backend/dsd/dsd");
        if p.exists() {
            return p;
        }
    }
    PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../../build/pyinstaller/dsd/dsd"))
}

fn show_error(win: &tauri::WebviewWindow, msg: &str) {
    let js = format!(
        "document.getElementById('status').textContent = {};",
        serde_json_string(msg)
    );
    let _ = win.eval(&js);
}

fn serde_json_string(s: &str) -> String {
    let escaped = s.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n");
    format!("\"{escaped}\"")
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            let win = app.get_webview_window("main").expect("main window");
            let port = free_port();
            let bin = backend_path(&handle);

            let log_dir = handle.path().app_log_dir().unwrap_or_else(|_| std::env::temp_dir());
            let _ = fs::create_dir_all(&log_dir);
            let log_path = log_dir.join("backend.log");
            let (out, err) = match File::create(&log_path) {
                Ok(f) => (Stdio::from(f.try_clone().unwrap()), Stdio::from(f)),
                Err(_) => (Stdio::null(), Stdio::null()),
            };
            let home = handle.path().home_dir().unwrap_or_else(|_| PathBuf::from("/"));

            match Command::new(&bin)
                .args(["ui", "--no-open", "--port", &port.to_string()])
                .env("DSD_APP", "1")
                .env("DSD_PARENT_PID", std::process::id().to_string())
                .current_dir(&home)
                .stdout(out)
                .stderr(err)
                .spawn()
            {
                Ok(child) => {
                    *handle.state::<Backend>().0.lock().unwrap() = Some(child);
                }
                Err(e) => {
                    show_error(&win, &format!("Could not start the dsd backend ({}): {e}", bin.display()));
                    return Ok(());
                }
            }

            thread::spawn(move || {
                let start = Instant::now();
                while start.elapsed() < Duration::from_secs(40) {
                    if TcpStream::connect(("127.0.0.1", port)).is_ok() {
                        if let Ok(url) = format!("http://127.0.0.1:{port}/").parse() {
                            let _ = win.navigate(url);
                        }
                        return;
                    }
                    thread::sleep(Duration::from_millis(120));
                }
                show_error(
                    &win,
                    &format!("The dsd backend didn't start. Log: {}", log_path.display()),
                );
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the dsd app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
