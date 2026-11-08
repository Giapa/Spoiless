#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::{mpsc, Mutex},
    time::Duration,
};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct Backend(Child);
impl Drop for Backend {
    fn drop(&mut self) {
        // Closing stdin also stops the backend if the desktop process crashes.
        self.0.stdin.take();
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn start_backend(app: &mut tauri::App) -> Result<Backend, Box<dyn std::error::Error>> {
    let name = if cfg!(windows) {
        "spoiless-backend.exe"
    } else {
        "spoiless-backend"
    };
    let executable = app.path().resource_dir()?.join("backend").join(name);
    let mut command = Command::new(executable);
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let mut backend = Backend(command.spawn()?);
    let stdout = backend
        .0
        .stdout
        .take()
        .ok_or("Backend output unavailable")?;
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let mut lines = BufReader::new(stdout).lines();
        if let Some(Ok(line)) = lines.next() {
            let _ = sender.send(line);
        }
        // Drain output so the child cannot block on a full pipe.
        for _ in lines {}
    });
    let line = receiver.recv_timeout(Duration::from_secs(60))?;
    let port: u16 = line
        .strip_prefix("SPOILESS_READY ")
        .ok_or("Backend failed to start")?
        .parse()?;
    if port == 0 {
        return Err("Invalid backend port".into());
    }
    let url = format!("http://127.0.0.1:{port}").parse()?;
    let allowed_url = format!("http://127.0.0.1:{port}");
    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("Spoiless")
        .inner_size(1200.0, 820.0)
        .min_inner_size(360.0, 560.0)
        // No remote content or Tauri IPC is needed by this window.
        .on_navigation(move |url| url.origin().ascii_serialization() == allowed_url)
        .build()?;
    Ok(backend)
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            match start_backend(app) {
                Ok(backend) => {
                    app.manage(Mutex::new(backend));
                }
                Err(error) => {
                    eprintln!("Spoiless startup failed: {error}");
                    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                        .title("Spoiless")
                        .inner_size(560.0, 300.0)
                        .build()?;
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Could not start Spoiless. Check that the bundled backend is installed.");
    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<Mutex<Backend>>() {
                if let Ok(mut backend) = state.lock() {
                    backend.0.stdin.take();
                    let _ = backend.0.kill();
                    let _ = backend.0.wait();
                }
            }
        }
    });
}
