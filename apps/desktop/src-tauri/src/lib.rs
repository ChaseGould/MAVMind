//! MAVMind desktop shell. The UI is a web app that talks to the vehicle and
//! agent services over HTTP/WebSocket; the shell itself only hosts the window.
//! It does not start the Python services.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running MAVMind");
}
