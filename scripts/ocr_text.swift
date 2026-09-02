// 本机离线 OCR：用 macOS 自带 Vision 识别图片里的文字，输出带坐标的 JSON。
// 不联网、不需要任何 API key。用法： swift ocr_text.swift a.png b.png
import Foundation
import Vision
import AppKit

let paths = Array(CommandLine.arguments.dropFirst())
var out: [[String: Any]] = []

for p in paths {
    guard let img = NSImage(contentsOfFile: p),
          let tiff = img.tiffRepresentation,
          let bmp = NSBitmapImageRep(data: tiff),
          let cg = bmp.cgImage else {
        out.append(["path": p, "error": "无法读取图片", "lines": []])
        continue
    }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hans", "en-US"]
    req.usesLanguageCorrection = false

    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do {
        try handler.perform([req])
    } catch {
        out.append(["path": p, "error": "\(error)", "lines": []])
        continue
    }

    var lines: [[String: Any]] = []
    for obs in (req.results ?? []) {
        guard let cand = obs.topCandidates(1).first else { continue }
        let bb = obs.boundingBox   // 左下角原点，归一化
        lines.append([
            "text": cand.string,
            "conf": Double(cand.confidence),
            "x": Double(bb.origin.x),
            "y": Double(1 - bb.origin.y - bb.height),   // 转成从上往下
            "w": Double(bb.width),
            "h": Double(bb.height),
        ])
    }
    lines.sort {
        let a = $0["y"] as! Double, b = $1["y"] as! Double
        if abs(a - b) > 0.01 { return a < b }
        return ($0["x"] as! Double) < ($1["x"] as! Double)
    }
    out.append(["path": p, "width": Int(bmp.pixelsWide), "height": Int(bmp.pixelsHigh), "lines": lines])
}

let data = try! JSONSerialization.data(withJSONObject: out, options: [])
print(String(data: data, encoding: .utf8)!)
