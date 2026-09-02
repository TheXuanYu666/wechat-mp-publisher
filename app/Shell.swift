// 步界社公众号生成器 · 原生 macOS 外壳
// 启动时拉起本地 Python 后端，用 WKWebView 显示界面；退出时结束后端进程。
import AppKit
import WebKit

let HOST = "127.0.0.1"
let PORT = 8765

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var tries = 0

    func applicationDidFinishLaunching(_ n: Notification) {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let skill = "\(home)/.kiro/skills/wechat-mp-publisher"
        let py = "\(skill)/.venv/bin/python"
        let server = "\(skill)/app/server.py"

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1040, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "步界社 · 公众号生成器"
        window.center()

        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: window.contentView!.bounds, configuration: cfg)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        window.contentView?.addSubview(web)
        window.makeKeyAndOrderFront(nil)

        showStatus("正在启动本地服务…")
        startBackend(py: py, server: server)
        waitAndLoad()
    }

    func showStatus(_ msg: String) {
        let html = """
        <html><head><meta charset='utf-8'><style>
        body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
        font:15px -apple-system,'PingFang SC',sans-serif;color:#1f9275;
        background:linear-gradient(#def7e2,#cceed9,#b8ede1)}
        .b{text-align:center}.s{width:22px;height:22px;margin:0 auto 12px;border:3px solid #cfe6dc;
        border-top-color:#1f9275;border-radius:50%;animation:r .7s linear infinite}
        @keyframes r{to{transform:rotate(360deg)}}</style></head>
        <body><div class='b'><div class='s'></div>\(msg)</div></body></html>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    func startBackend(py: String, server: String) {
        guard FileManager.default.fileExists(atPath: py),
              FileManager.default.fileExists(atPath: server) else {
            showStatus("找不到后端文件，App 包不完整")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [server, "--no-browser"]
        // 后端输出落盘，出问题能查（原来丢弃导致故障不可见）
        let logPath = NSString(string: "~/.kiro/logs/mp-app-server.log").expandingTildeInPath
        FileManager.default.createFile(atPath: logPath, contents: nil)
        if let fh = FileHandle(forWritingAtPath: logPath) {
            fh.seekToEndOfFile()
            p.standardOutput = fh
            p.standardError = fh
        }
        do { try p.run(); backend = p } catch { showStatus("后端启动失败：\(error)") }
    }

    /// 轮询等后端起来再加载页面，避免白屏
    func waitAndLoad() {
        let url = URL(string: "http://\(HOST):\(PORT)/api/context")!
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { data, _, _ in
            DispatchQueue.main.async {
                if data != nil {
                    self.web.load(URLRequest(url: URL(string: "http://\(HOST):\(PORT)/")!))
                } else {
                    self.tries += 1
                    if self.tries > 40 {
                        self.showStatus("本地服务启动超时。日志：~/.kiro/logs/mp-app-server.log")
                        return
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitAndLoad() }
                }
            }
        }.resume()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ n: Notification) {
        backend?.terminate()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.activate(ignoringOtherApps: true)
app.run()
