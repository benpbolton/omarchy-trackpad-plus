// Two-minute check of macOS trackpad scrolling for Trackpad Plus.
//
//   swiftc -O tools/macos/scroll-probe.swift -o /tmp/scroll-probe && /tmp/scroll-probe scroll.csv
//   python3 tools/macos/export-profile.py --check-scroll scroll.csv --profile PROFILE.json [--write]
//   Option: --seconds N (default 120).
//
// A full-screen scroll view records every scroll event three ways: AppKit's deltas, the
// CGEvent scroll fields, and the HID event behind them — the multitouch driver's raw delta and
// IOHIDScrollAccelerator's accelerated copy — read with the same private calls WebKit uses
// (CGEventCopyIOHIDEvent, IOHIDEvent getters). It also records AppKit's public NSTouch
// positions for both fingers and how far the scroll view actually moved. Like probe.swift it
// does not start the MultitouchSupport framework, which changes how macOS moves the pointer.
// No permissions are needed; nothing is sent anywhere; the CSV stays where you ask.
import AppKit
import Foundation

let arguments = Array(CommandLine.arguments.dropFirst())
let recordSeconds = arguments.firstIndex(of: "--seconds").flatMap { Double(arguments[$0 + 1]) } ?? 120.0
let idleLimitSeconds = 300.0

// MARK: Private HID accessors, looked up at run time so a missing symbol only blanks a column.

typealias CopyHIDEvent = @convention(c) (UnsafeMutableRawPointer) -> UnsafeMutableRawPointer?
typealias GetFloat = @convention(c) (UnsafeMutableRawPointer, UInt32) -> Double
typealias GetU64 = @convention(c) (UnsafeMutableRawPointer) -> UInt64
typealias GetU32 = @convention(c) (UnsafeMutableRawPointer) -> UInt32
typealias GetU16 = @convention(c) (UnsafeMutableRawPointer) -> UInt16
typealias GetU8 = @convention(c) (UnsafeMutableRawPointer) -> UInt8
typealias GetPointer = @convention(c) (UnsafeMutableRawPointer) -> UnsafeMutableRawPointer?
typealias CopyAttachment = @convention(c) (UnsafeMutableRawPointer, UnsafeMutableRawPointer, UInt32) -> UnsafeMutableRawPointer?

func symbol<T>(_ name: String, _ type: T.Type) -> T? {
    guard let pointer = dlsym(UnsafeMutableRawPointer(bitPattern: -2), name) else { return nil }  // RTLD_DEFAULT
    return unsafeBitCast(pointer, to: type)
}

let copyHIDEvent = symbol("CGEventCopyIOHIDEvent", CopyHIDEvent.self)
let hidFloat = symbol("IOHIDEventGetFloatValue", GetFloat.self)
let hidTime = symbol("IOHIDEventGetTimeStamp", GetU64.self)
let hidType = symbol("IOHIDEventGetType", GetU32.self)
let hidFlags = symbol("IOHIDEventGetEventFlags", GetU32.self)
let hidPhase = symbol("IOHIDEventGetPhase", GetU16.self)
let hidMomentum = symbol("IOHIDEventGetScrollMomentum", GetU8.self)
let hidChildren = symbol("IOHIDEventGetChildren", GetPointer.self)
let hidAttachment = symbol("_IOHIDEventCopyAttachment", CopyAttachment.self)

let scrollType: UInt32 = 6                 // kIOHIDEventTypeScroll
let scrollX: UInt32 = (6 << 16) | 0        // kIOHIDEventFieldScrollX
let scrollY: UInt32 = (6 << 16) | 1        // kIOHIDEventFieldScrollY
let acceleratedFlag: UInt32 = 0x0001_0000  // kIOHIDAccelerated
let dispatchRateKey = "ScrollMomentumDispatchRate" as CFString

var timebase = mach_timebase_info_data_t()
mach_timebase_info(&timebase)

func seconds(_ ticks: UInt64) -> Double {
    Double(ticks) * Double(timebase.numer) / Double(timebase.denom) / 1e9
}

struct HIDScroll {
    var time = Double.nan, rawX = Double.nan, rawY = Double.nan, accelX = Double.nan, accelY = Double.nan
    var children = -1, flags = -1, phase = -1, momentum = -1, dispatchRate = Double.nan
}

func hidScroll(_ cg: CGEvent) -> HIDScroll {
    var result = HIDScroll()
    guard let copy = copyHIDEvent, let event = copy(Unmanaged.passUnretained(cg).toOpaque()) else { return result }
    defer { Unmanaged<AnyObject>.fromOpaque(event).release() }
    if let hidTime { result.time = seconds(hidTime(event)) }
    if let hidFloat {
        result.rawX = hidFloat(event, scrollX)
        result.rawY = hidFloat(event, scrollY)
    }
    if let hidFlags { result.flags = Int(hidFlags(event)) }
    if let hidPhase { result.phase = Int(hidPhase(event)) }
    if let hidMomentum { result.momentum = Int(hidMomentum(event)) }
    if let hidAttachment, let value = hidAttachment(event, Unmanaged.passUnretained(dispatchRateKey).toOpaque(), 0) {
        if let number = Unmanaged<AnyObject>.fromOpaque(value).takeRetainedValue() as? NSNumber {
            result.dispatchRate = number.doubleValue
        }
    }
    // IOHIDPointerScrollFilter appends the accelerated copy as a child flagged kIOHIDAccelerated.
    if let hidChildren, let hidFloat, let hidFlags, let hidType, let pointer = hidChildren(event) {
        let children = Unmanaged<CFArray>.fromOpaque(pointer).takeUnretainedValue()
        result.children = CFArrayGetCount(children)
        for index in 0..<CFArrayGetCount(children) {
            guard let raw = CFArrayGetValueAtIndex(children, index) else { continue }
            let child = UnsafeMutableRawPointer(mutating: raw)
            if hidType(child) == scrollType && hidFlags(child) & acceleratedFlag != 0 {
                result.accelX = hidFloat(child, scrollX)
                result.accelY = hidFloat(child, scrollY)
            }
        }
    }
    return result
}

// AppKit's private unaccelerated deltas and scroll count, which WebKit also reads.
func privateValue(_ event: NSEvent, _ name: String) -> Double {
    let selector = NSSelectorFromString(name)
    guard event.responds(to: selector), let method = class_getInstanceMethod(type(of: event), selector) else {
        return .nan
    }
    let implementation = method_getImplementation(method)
    typealias CountGetter = @convention(c) (AnyObject, Selector) -> UInt
    typealias FloatGetter = @convention(c) (AnyObject, Selector) -> CGFloat
    if name == "_scrollCount" {
        return Double(unsafeBitCast(implementation, to: CountGetter.self)(event, selector) & 0xFFFF_FFFF)
    }
    return Double(unsafeBitCast(implementation, to: FloatGetter.self)(event, selector))
}

func csv(_ value: Double) -> String { value.isNaN ? "" : "\(value)" }

// MARK: Recording

final class Log {
    private var lines: [String] = []
    private(set) var scrollEvents = 0
    private(set) var touchFrames = 0
    private(set) var census = 0
    var coverage = [String: Int]()

    func add(_ line: String) { lines.append(line) }
    func scroll(_ line: String) { lines.append(line); scrollEvents += 1 }
    func touch(_ line: String) { lines.append(line); touchFrames += 1 }
    func field(_ line: String) { lines.append(line); census += 1 }
    func count(_ key: String) { coverage[key, default: 0] += 1 }

    func write(to url: URL, header: [String]) throws {
        try (header + lines).joined(separator: "\n").appending("\n").write(to: url, atomically: true, encoding: .utf8)
    }
}

let log = Log()

final class ProbeWindow: NSWindow {
    override var canBecomeKey: Bool { true }
}

// The page that scrolls: stripes every 50 points so movement is visible, and NSTouch input.
final class Paper: NSView {
    override var isFlipped: Bool { true }
    // Responsive scrolling takes a gesture's changed and momentum events off -sendEvent:, where
    // the local monitor never sees them; without it every event passes the monitor.
    override class var isCompatibleWithResponsiveScrolling: Bool { false }
    override func touchesBegan(with event: NSEvent) { recordTouches(event) }
    override func touchesMoved(with event: NSEvent) { recordTouches(event) }
    override func touchesEnded(with event: NSEvent) { recordTouches(event) }
    override func touchesCancelled(with event: NSEvent) { recordTouches(event) }
    var touchBegan: (() -> Void)?

    override func draw(_ dirtyRect: NSRect) {
        NSColor(calibratedWhite: 0.11, alpha: 1).setFill()
        dirtyRect.fill()
        NSColor(calibratedWhite: 0.2, alpha: 1).setFill()
        var y = (dirtyRect.minY / 50).rounded(.down) * 50
        while y < dirtyRect.maxY {
            NSRect(x: dirtyRect.minX, y: y, width: dirtyRect.width, height: 1).fill()
            y += 50
        }
        var x = (dirtyRect.minX / 50).rounded(.down) * 50
        while x < dirtyRect.maxX {
            NSRect(x: x, y: dirtyRect.minY, width: 1, height: dirtyRect.height).fill()
            x += 50
        }
    }

    // NSTouch positions are normalised to the trackpad; deviceSize is in points (1/72 in).
    func recordTouches(_ event: NSEvent) {
        let touches = event.touches(matching: .any, in: self)
        let touching = touches.filter { $0.phase != .ended && $0.phase != .cancelled }
        if touches.contains(where: { $0.phase == .began }) { touchBegan?() }
        let now = ProcessInfo.processInfo.systemUptime
        var fields = ["N", "\(event.timestamp)", "\(now)", "\(touching.count)"]
        let size = (touching.first ?? touches.first)?.deviceSize ?? .zero
        fields += ["\(size.width)", "\(size.height)"]
        for touch in touching.prefix(2) {
            fields += ["\(touch.identity.hash)", "\(touch.normalizedPosition.x)", "\(touch.normalizedPosition.y)",
                       "\(touch.phase.rawValue)"]
        }
        log.touch(fields.joined(separator: ","))
    }
}

// Instructions sit above the page but never take its events.
final class Overlay: NSView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    var started: TimeInterval?

    override func draw(_ dirtyRect: NSRect) {
        let now = ProcessInfo.processInfo.systemUptime
        let remaining = started.map { max(0, recordSeconds - (now - $0)) }
        let c = log.coverage
        var text = """
        Trackpad Plus · scroll check (about \(Int(recordSeconds / 60)) minutes)

        Scroll this page with TWO fingers. Do not click. Mix these in any order:
          1. slow, careful scrolling — stop, then lift your fingers
          2. ordinary scrolling at a normal pace
          3. flicks: lift while moving and let the page glide to a stop (soft and hard)
          4. a flick, then touch the trackpad to stop the glide
          5. three or four quick flicks in a row, the same direction
          6. a few sideways scrolls and flicks

        """
        text += remaining.map { String(format: "Recording… %.0f s left", $0) } ?? "Recording starts with the first scroll."
        text += "\n\(log.scrollEvents) scroll events · \(log.touchFrames) touch frames"
        if log.scrollEvents > 50 && log.touchFrames == 0 {
            text += "\nNO TOUCHES ARRIVING: click once in the middle of the page, then keep scrolling."
        }
        text += "\n\nCoverage   slow \(bar(c["slow", default: 0], 600))   normal \(bar(c["normal", default: 0], 600))"
        text += "   fast \(bar(c["fast", default: 0], 200))"
        text += "\n           flicks \(bar(c["flick", default: 0], 25))   stopped \(bar(c["stopped", default: 0], 6))"
        text += "   repeated \(bar(c["repeat", default: 0], 8))   sideways \(bar(c["sideways", default: 0], 300))"
        if hidFloat == nil || copyHIDEvent == nil {
            text += "\n\nHID values are unavailable on this macOS; the check will be limited."
        }
        text += "\n\nEsc stops early."
        let style = NSMutableParagraphStyle()
        style.lineSpacing = 6
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: 17, weight: .regular),
            .foregroundColor: NSColor(calibratedWhite: 0.92, alpha: 1), .paragraphStyle: style]
        let box = bounds.insetBy(dx: 60, dy: 60)
        NSColor(calibratedWhite: 0, alpha: 0.55).setFill()
        NSBezierPath(roundedRect: box.insetBy(dx: -20, dy: -20), xRadius: 12, yRadius: 12).fill()
        NSAttributedString(string: text, attributes: attributes).draw(in: box)
    }

    func bar(_ count: Int, _ target: Int) -> String {
        let filled = min(10, count * 10 / target)
        return String(repeating: "█", count: filled) + String(repeating: "·", count: 10 - filled)
    }
}

guard let outputPath = arguments.first, !outputPath.hasPrefix("--") else {
    FileHandle.standardError.write("Usage: scroll-probe OUTPUT.csv [--seconds N]\n".data(using: .utf8)!)
    exit(2)
}
let output = URL(fileURLWithPath: outputPath)
let app = NSApplication.shared
app.setActivationPolicy(.regular)
NSEvent.isMouseCoalescingEnabled = false  // one row per HID event

let screen = NSScreen.screens.first { screen in
    let id = (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value ?? 0
    return CGDisplayIsBuiltin(id) != 0
} ?? NSScreen.main!
let window = ProbeWindow(contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
window.level = .mainMenu + 1
let root = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
let scrollView = NSScrollView(frame: root.bounds)
// Touches go to the view under the pointer, so keep the page the only view there: no scrollers.
scrollView.hasVerticalScroller = false
scrollView.hasHorizontalScroller = false
scrollView.autoresizingMask = [.width, .height]
let paper = Paper(frame: NSRect(x: 0, y: 0, width: 1_000_000, height: 4_000_000))
paper.allowedTouchTypes = [.indirect]
paper.wantsRestingTouches = true
scrollView.documentView = paper
let overlay = Overlay(frame: root.bounds)
overlay.autoresizingMask = [.width, .height]
root.addSubview(scrollView)
root.addSubview(overlay)
window.contentView = root
// Start far from every edge so rubber-banding never limits a stroke.
scrollView.contentView.scroll(to: NSPoint(x: 500_000, y: 2_000_000))
scrollView.reflectScrolledClipView(scrollView.contentView)
scrollView.contentView.postsBoundsChangedNotifications = true
_ = NotificationCenter.default.addObserver(forName: NSView.boundsDidChangeNotification, object: scrollView.contentView,
                                           queue: nil) { _ in
    let origin = scrollView.contentView.bounds.origin
    log.add("V,\(ProcessInfo.processInfo.systemUptime),\(origin.x),\(origin.y)")
}

var lastMomentumBegan: TimeInterval?
var momentumActive = false
paper.touchBegan = {
    if momentumActive { log.count("stopped"); momentumActive = false }
}

let fieldNames: [(String, CGEventField)] = [
    ("point", .scrollWheelEventPointDeltaAxis1), ("point", .scrollWheelEventPointDeltaAxis2),
    ("fixed", .scrollWheelEventFixedPtDeltaAxis1), ("fixed", .scrollWheelEventFixedPtDeltaAxis2),
    ("line", .scrollWheelEventDeltaAxis1), ("line", .scrollWheelEventDeltaAxis2)]

func record(_ event: NSEvent) {
    guard let cg = event.cgEvent else { return }
    let now = ProcessInfo.processInfo.systemUptime
    if overlay.started == nil { overlay.started = now }
    let hid = hidScroll(cg)
    let phase = event.phase.rawValue, momentum = event.momentumPhase.rawValue
    // Axis 1 is vertical and axis 2 horizontal; columns below are x then y.
    let values = fieldNames.map { cg.getDoubleValueField($0.1) }
    var row = ["S", "\(event.timestamp)", "\(now)", "\(phase)", "\(momentum)",
               "\(event.scrollingDeltaX)", "\(event.scrollingDeltaY)",
               event.hasPreciseScrollingDeltas ? "1" : "0", event.isDirectionInvertedFromDevice ? "1" : "0",
               csv(privateValue(event, "_unacceleratedScrollingDeltaX")),
               csv(privateValue(event, "_unacceleratedScrollingDeltaY")), csv(privateValue(event, "_scrollCount")),
               "\(values[1])", "\(values[0])", "\(values[3])", "\(values[2])", "\(values[5])", "\(values[4])",
               "\(cg.getIntegerValueField(.scrollWheelEventIsContinuous))",
               "\(cg.getIntegerValueField(.scrollWheelEventScrollPhase))",
               "\(cg.getIntegerValueField(.scrollWheelEventMomentumPhase))",
               "\(cg.getIntegerValueField(.scrollWheelEventScrollCount))"]
    row += [csv(hid.time), csv(hid.rawX), csv(hid.rawY), csv(hid.accelX), csv(hid.accelY),
            "\(hid.children)", "\(hid.flags)", "\(hid.phase)", "\(hid.momentum)", csv(hid.dispatchRate)]
    log.scroll(row.joined(separator: ","))
    // Every non-zero CGEvent field of the first scroll events, to find fields this list misses.
    if log.census < 400 {
        var census: [String] = []
        for raw in 0..<256 {
            if let field = CGEventField(rawValue: UInt32(raw)) {
                let value = cg.getDoubleValueField(field)
                if value != 0 { census.append("\(raw)=\(value)") }
            }
        }
        log.field("F,\(event.timestamp)," + census.joined(separator: ";"))
    }
    // Rough coverage only; the check classifies strokes from the recording itself.
    let size = max(abs(event.scrollingDeltaX), abs(event.scrollingDeltaY))
    if phase != 0 && size > 0 {
        log.count(size < 2 ? "slow" : size < 15 ? "normal" : "fast")
        if abs(event.scrollingDeltaX) > abs(event.scrollingDeltaY) { log.count("sideways") }
    }
    if event.momentumPhase == .began {
        log.count("flick")
        if let previous = lastMomentumBegan, event.timestamp - previous < 1.5 { log.count("repeat") }
        lastMomentumBegan = event.timestamp
        momentumActive = true
    } else if event.momentumPhase == .ended || event.momentumPhase == .cancelled {
        momentumActive = false
    }
}

let natural = UserDefaults.standard.object(forKey: "com.apple.swipescrolldirection") as? Bool ?? true
let header = [
    "# trackpad-plus scroll-probe 1",
    "# screen_points,\(screen.frame.width),\(screen.frame.height),backing_scale,\(screen.backingScaleFactor)",
    "# natural,\(natural ? 1 : 0)",
    "# hid,\(copyHIDEvent != nil && hidFloat != nil ? 1 : 0),children,\(hidChildren != nil ? 1 : 0),"
        + "attachment,\(hidAttachment != nil ? 1 : 0)",
    "# timebase,\(timebase.numer),\(timebase.denom)",
    "# columns S,timestamp,received,phase,momentum_phase,scrolling_dx,scrolling_dy,precise,inverted,"
        + "unaccel_dx,unaccel_dy,scroll_count,cg_point_dx,cg_point_dy,cg_fixed_dx,cg_fixed_dy,cg_line_dx,cg_line_dy,"
        + "cg_continuous,cg_scroll_phase,cg_momentum_phase,cg_scroll_count,"
        + "hid_time,hid_raw_x,hid_raw_y,hid_accel_x,hid_accel_y,hid_children,hid_flags,hid_phase,hid_momentum,hid_dispatch_rate",
    "# columns N,timestamp,received,touching,device_width_pt,device_height_pt[,identity,normalized_x,normalized_y,phase]…",
    "# columns V,received,origin_x,origin_y",
    "# columns F,timestamp,field=value;…",
]

var done = false
func finish() {
    guard !done else { return }
    done = true
    do {
        try log.write(to: output, header: header)
        print("Wrote \(output.path): \(log.scrollEvents) scroll events, \(log.touchFrames) touch frames.")
    } catch {
        FileHandle.standardError.write("Could not write \(output.path): \(error)\n".data(using: .utf8)!)
    }
    app.terminate(nil)
}
_ = NSEvent.addLocalMonitorForEvents(matching: [.scrollWheel]) { event in
    record(event)
    return event
}
_ = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) { event in
    if event.keyCode == 53 { finish() }  // Escape
    return nil
}
let opened = ProcessInfo.processInfo.systemUptime
Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
    let now = ProcessInfo.processInfo.systemUptime
    if let started = overlay.started, now - started >= recordSeconds { finish() }
    if overlay.started == nil && now - opened > idleLimitSeconds { finish() }
    overlay.needsDisplay = true
}
window.makeKeyAndOrderFront(nil)
window.makeFirstResponder(scrollView)
app.activate(ignoringOtherApps: true)
app.run()
