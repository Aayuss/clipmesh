import AppKit
import Foundation

func fail(_ message: String) -> Never {
    fputs(message + "\n", stderr)
    exit(1)
}

func setImage() {
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: 3,
        pixelsHigh: 2,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else { fail("could not create image") }

    let colors: [NSColor] = [.red, .green, .blue, .yellow, .magenta, .cyan]
    for y in 0..<2 {
        for x in 0..<3 {
            rep.setColor(colors[y * 3 + x], atX: x, y: y)
        }
    }
    guard let data = rep.representation(using: .png, properties: [:]) else { fail("could not encode PNG") }
    let board = NSPasteboard.general
    board.clearContents()
    guard board.setData(data, forType: .png) else { fail("could not write pasteboard image") }
    print("SET_IMAGE 3x2")
}

func imageInfo() {
    let board = NSPasteboard.general
    let data = board.data(forType: .png) ?? board.data(forType: .tiff)
    guard let data, let rep = NSBitmapImageRep(data: data) else {
        print("NONE")
        return
    }
    print("\(rep.pixelsWide)x\(rep.pixelsHigh)")
}

let args = CommandLine.arguments
if args.count < 2 { fail("usage: macos-pasteboard-helper <set-image|image-info>") }
switch args[1] {
case "set-image": setImage()
case "image-info": imageInfo()
default: fail("unknown command")
}
