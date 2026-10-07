// HummingScore — 跨平台桌面外壳
// 前端为纯静态 Web 资源 (src/，即 frontendDist)，全部功能在 webview 内完成，
// 无需本地 server / Python。麦克风录音走 WebAudio getUserMedia，
// 由各平台的 webview + 系统权限机制处理。

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running HummingScore");
}