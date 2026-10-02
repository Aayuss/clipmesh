import Cocoa
import Foundation
import Darwin
import ImageIO
import UniformTypeIdentifiers

// MARK: - Ember design tokens

enum CMColor {
    static func hex(_ value: UInt32, _ alpha: CGFloat = 1) -> NSColor {
        NSColor(srgbRed: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255, blue: CGFloat(value & 0xFF) / 255, alpha: alpha)
    }
    static let background = hex(0x131314)
    static let surface = hex(0x222222)
    static let accent = hex(0xE55F11)
    static let accentHover = hex(0xEE6A1D)
    static let accentPressed = hex(0xC9520E)
    static let accentSoft = hex(0xE55F11, 0.14)
    static let text = NSColor.white
    static let textSoft = hex(0xDDDDDD)
    static let textMuted = NSColor(white: 1, alpha: 0.5)
    static let textFaint = NSColor(white: 1, alpha: 0.35)
    static let line = NSColor(white: 1, alpha: 0.08)
    static let fill05 = NSColor(white: 1, alpha: 0.05)
    static let fill06 = NSColor(white: 1, alpha: 0.06)
    static let fill07 = NSColor(white: 1, alpha: 0.07)
    static let fill11 = NSColor(white: 1, alpha: 0.11)
    static let fill20 = NSColor(white: 1, alpha: 0.20)
    static let positive = hex(0x3FD05E)
    static let negative = hex(0xFF6B5A)
    static let negativeHover = hex(0xFF7D6E)
    static let negativePressed = hex(0xE55A4A)
    static let toggleOff = hex(0x3A3A3A)
    static let glow = hex(0x272B22)
}

/// Sora is bundled under Contents/Resources/Fonts (ATSApplicationFontsPath).
/// Every accessor falls back to the system UI font.
enum CMFont {
    private static var registered = false

    static func registerBundledFonts() {
        guard !registered else { return }
        registered = true
        guard NSFont(name: "Sora-Regular", size: 12) == nil,
              let folder = Bundle.main.resourceURL?.appendingPathComponent("Fonts", isDirectory: true),
              let files = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
        else { return }
        for file in files where file.pathExtension.lowercased() == "ttf" {
            CTFontManagerRegisterFontsForURL(file as CFURL, .process, nil)
        }
    }

    private static func named(_ name: String, _ size: CGFloat, _ weight: NSFont.Weight) -> NSFont {
        NSFont(name: name, size: size) ?? .systemFont(ofSize: size, weight: weight)
    }
    static func regular(_ size: CGFloat) -> NSFont { named("Sora-Regular", size, .regular) }
    static func medium(_ size: CGFloat) -> NSFont { named("Sora-Medium", size, .medium) }
    static func semibold(_ size: CGFloat) -> NSFont { named("Sora-SemiBold", size, .semibold) }
    static func bold(_ size: CGFloat) -> NSFont { named("Sora-Bold", size, .bold) }
}

enum CMMotion {
    static var reduce: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
    static let ease = CAMediaTimingFunction(controlPoints: 0.2, 0, 0, 1)

    static func basic(_ keyPath: String, from: Any?, to: Any?, duration: CFTimeInterval) -> CABasicAnimation {
        let animation = CABasicAnimation(keyPath: keyPath)
        animation.fromValue = from
        animation.toValue = to
        animation.duration = duration
        animation.timingFunction = ease
        return animation
    }

    /// Critically-damped-ish spring (damping ratio ≈ 0.84, stiffness ≈ 520).
    static func spring(_ keyPath: String, from: Any?, to: Any?, damping ratio: CGFloat = 0.84, stiffness: CGFloat = 520) -> CAAnimation {
        guard !reduce else { return basic(keyPath, from: from, to: to, duration: 0.16) }
        let spring = CASpringAnimation(keyPath: keyPath)
        spring.mass = 1
        spring.stiffness = stiffness
        spring.damping = 2 * ratio * sqrt(stiffness)
        spring.initialVelocity = 0
        spring.fromValue = from
        spring.toValue = to
        spring.duration = spring.settlingDuration
        return spring
    }

    /// Sets a layer colour (or any animatable key) and animates from what is on screen.
    static func animate(_ layer: CALayer?, key: String = "backgroundColor", to value: CGColor?, duration: CFTimeInterval = 0.16) {
        guard let layer else { return }
        let from = (layer.presentation() ?? layer).value(forKey: key)
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        layer.setValue(value, forKey: key)
        CATransaction.commit()
        layer.add(basic(key, from: from, to: value, duration: duration), forKey: key)
    }

    /// A transform that acts around the layer centre whatever its anchor point is.
    static func centered(_ transform: CATransform3D, layer: CALayer) -> CATransform3D {
        let dx = (0.5 - layer.anchorPoint.x) * layer.bounds.width
        let dy = (0.5 - layer.anchorPoint.y) * layer.bounds.height
        return CATransform3DConcat(CATransform3DConcat(CATransform3DMakeTranslation(-dx, -dy, 0), transform), CATransform3DMakeTranslation(dx, dy, 0))
    }

    static func press(_ view: NSView, down: Bool) {
        guard !reduce, let layer = view.layer else { return }
        let from = (layer.presentation() ?? layer).transform
        let to = down ? centered(CATransform3DMakeScale(0.96, 0.96, 1), layer: layer) : CATransform3DIdentity
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        layer.transform = to
        CATransaction.commit()
        let animation = down
            ? basic("transform", from: NSValue(caTransform3D: from), to: NSValue(caTransform3D: to), duration: 0.1)
            : spring("transform", from: NSValue(caTransform3D: from), to: NSValue(caTransform3D: to), damping: 0.62, stiffness: 600)
        layer.add(animation, forKey: "press")
        CATransaction.flush()
    }

    /// Fade in while sliding `dy` points (positive = from above in flipped space is not assumed;
    /// translation is applied in the layer's own space).
    static func enter(_ view: NSView, dx: CGFloat = 0, dy: CGFloat = 0, duration: CFTimeInterval = 0.22) {
        guard let layer = view.layer else { return }
        layer.add(basic("opacity", from: 0, to: 1, duration: duration), forKey: "enterOpacity")
        if !reduce && (dx != 0 || dy != 0) {
            layer.add(basic("transform", from: NSValue(caTransform3D: CATransform3DMakeTranslation(dx, dy, 0)), to: NSValue(caTransform3D: CATransform3DIdentity), duration: duration), forKey: "enterSlide")
        }
    }

    /// One full clockwise turn around the centre (used by refresh buttons).
    static func spin(_ view: NSView) {
        guard !reduce, let layer = view.layer else { return }
        let steps = 12
        let values = (0...steps).map { step -> NSValue in
            let angle = -CGFloat(step) / CGFloat(steps) * 2 * .pi
            return NSValue(caTransform3D: centered(CATransform3DMakeRotation(angle, 0, 0, 1), layer: layer))
        }
        let animation = CAKeyframeAnimation(keyPath: "transform")
        animation.values = values
        animation.duration = 0.55
        animation.timingFunction = ease
        layer.add(animation, forKey: "spin")
    }

    static func pulse(_ layer: CALayer?, enabled: Bool, cycles: Float = 6) {
        guard let layer else { return }
        if !enabled || reduce { layer.removeAnimation(forKey: "pulse"); return }
        guard layer.animation(forKey: "pulse") == nil else { return }
        let animation = CABasicAnimation(keyPath: "opacity")
        animation.fromValue = 1
        animation.toValue = 0.3
        animation.duration = 0.9
        animation.autoreverses = true
        animation.repeatCount = cycles
        animation.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        layer.add(animation, forKey: "pulse")
    }

    /// Runs `block` after `delay` even while a modal session or tracking loop is active.
    static func after(_ delay: TimeInterval, _ block: @escaping () -> Void) {
        let timer = Timer(timeInterval: delay, repeats: false) { _ in block() }
        RunLoop.main.add(timer, forMode: .common)
    }
}

// MARK: - Small view helpers

func cmLabel(_ text: String, _ font: NSFont, _ color: NSColor = CMColor.text, wrap: Bool = false) -> NSTextField {
    let label = wrap ? NSTextField(wrappingLabelWithString: text) : NSTextField(labelWithString: text)
    label.font = font
    label.textColor = color
    label.translatesAutoresizingMaskIntoConstraints = false
    if !wrap {
        label.lineBreakMode = .byTruncatingTail
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    }
    return label
}

func cmSection(_ text: String) -> NSTextField { cmLabel(text, CMFont.medium(13), CMColor.textMuted) }

func cmTitle(_ text: String) -> NSTextField {
    let label = NSTextField(labelWithAttributedString: NSAttributedString(string: text, attributes: [
        .font: CMFont.semibold(26), .foregroundColor: CMColor.text, .kern: -0.3,
    ]))
    label.translatesAutoresizingMaskIntoConstraints = false
    return label
}

func cmSpacer() -> NSView {
    let view = NSView()
    view.translatesAutoresizingMaskIntoConstraints = false
    view.setContentHuggingPriority(.init(1), for: .horizontal)
    view.setContentCompressionResistancePriority(.init(1), for: .horizontal)
    return view
}

func cmHStack(_ views: [NSView], spacing: CGFloat = 10) -> NSStackView {
    let stack = NSStackView(views: views)
    stack.orientation = .horizontal
    stack.alignment = .centerY
    stack.spacing = spacing
    stack.translatesAutoresizingMaskIntoConstraints = false
    return stack
}

func cmVStack(_ views: [NSView], spacing: CGFloat = 3) -> NSStackView {
    let stack = NSStackView(views: views)
    stack.orientation = .vertical
    stack.alignment = .leading
    stack.spacing = spacing
    stack.translatesAutoresizingMaskIntoConstraints = false
    return stack
}

func cmListStack() -> NSStackView {
    let stack = cmVStack([], spacing: 2)
    stack.setHuggingPriority(.defaultHigh, for: .vertical)
    return stack
}

func cmSymbol(_ name: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = CMColor.textMuted) -> NSImageView {
    let view = NSImageView()
    view.image = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: size, weight: weight))
    view.contentTintColor = color
    view.translatesAutoresizingMaskIntoConstraints = false
    view.setContentHuggingPriority(.required, for: .horizontal)
    return view
}

func cmByteString(_ bytes: Int64) -> String { ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file) }

private final class CMFlippedView: NSView { override var isFlipped: Bool { true } }

/// Overlay, auto-hiding scrollers only — never the legacy always-visible track,
/// even when the system preference (or an attached mouse) asks for it.
final class CMScrollView: NSScrollView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        drawsBackground = false
        contentView.drawsBackground = false
        autohidesScrollers = true
        automaticallyAdjustsContentInsets = false
        contentInsets = NSEdgeInsets()
        super.scrollerStyle = .overlay
        translatesAutoresizingMaskIntoConstraints = false
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override var scrollerStyle: NSScroller.Style {
        get { .overlay }
        set { super.scrollerStyle = .overlay }
    }
    override func tile() {
        if super.scrollerStyle != .overlay { super.scrollerStyle = .overlay }
        super.tile()
    }
}

/// Layer-backed view with optional hover tracking.
class CMHoverView: NSView {
    var tracksHover = false { didSet { updateTrackingAreas() } }
    private(set) var isHovering = false
    private var hoverArea: NSTrackingArea?

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let hoverArea { removeTrackingArea(hoverArea) }
        hoverArea = nil
        guard tracksHover else { return }
        let area = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeInActiveApp, .inVisibleRect], owner: self, userInfo: nil)
        addTrackingArea(area)
        hoverArea = area
    }
    override func mouseEntered(with event: NSEvent) { isHovering = true; hoverChanged() }
    override func mouseExited(with event: NSEvent) { isHovering = false; hoverChanged() }
    func hoverChanged() {}
    func resyncHover() {
        guard let window else { return }
        let inside = bounds.contains(convert(window.mouseLocationOutsideOfEventStream, from: nil))
        if inside != isHovering { isHovering = inside; hoverChanged() }
    }
}

class CMBox: CMHoverView {
    init(fill: NSColor? = nil, radius: CGFloat = 0, border: NSColor? = nil) {
        super.init(frame: .zero)
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        layer?.backgroundColor = fill?.cgColor
        layer?.cornerRadius = radius
        if let border {
            layer?.borderWidth = 1
            layer?.borderColor = border.cgColor
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
}

// MARK: - Pill button

final class CMPillButton: NSButton {
    enum Style { case primary, secondary, destructive, plain, text, overlay }

    var style: Style { didSet { refreshAppearance(animated: true) } }
    var handler: (() -> Void)?
    var tint: NSColor? { didSet { refreshAppearance(animated: false) } }
    /// Plain style only: resting background and hover foreground overrides.
    var restingFill: NSColor? { didSet { refreshAppearance(animated: true) } }
    var hoverTint: NSColor? { didSet { refreshAppearance(animated: false) } }
    private let pillHeight: CGFloat
    private var label: String
    private var hovering = false
    private var pressed = false
    private var hoverArea: NSTrackingArea?

    init(_ title: String, symbol: String? = nil, style: Style = .secondary, height: CGFloat = 34, handler: (() -> Void)? = nil) {
        self.style = style
        self.pillHeight = height
        self.label = title
        self.handler = handler
        super.init(frame: NSRect(x: 0, y: 0, width: height, height: height))
        isBordered = false
        setButtonType(.momentaryPushIn)
        (cell as? NSButtonCell)?.highlightsBy = []
        (cell as? NSButtonCell)?.showsStateBy = []
        wantsLayer = true
        focusRingType = .none
        layer?.cornerRadius = height / 2
        target = self
        action = #selector(fire)
        translatesAutoresizingMaskIntoConstraints = false
        self.title = title
        imageHugsTitle = true
        if let symbol { setSymbol(symbol) }
        imagePosition = symbol == nil ? .noImage : (title.isEmpty ? .imageOnly : .imageLeading)
        setContentHuggingPriority(.required, for: .horizontal)
        setContentCompressionResistancePriority(.required, for: .horizontal)
        refreshAppearance(animated: false)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func setSymbol(_ name: String) {
        let size: CGFloat = label.isEmpty ? (pillHeight >= 34 ? 15 : 12) : 12
        image = NSImage(systemSymbolName: name, accessibilityDescription: label.isEmpty ? (toolTip ?? name) : label)?
            .withSymbolConfiguration(.init(pointSize: size, weight: .semibold))
    }

    func setLabel(_ text: String) {
        guard text != label else { return }
        label = text
        title = text
        refreshAppearance(animated: false)
        invalidateIntrinsicContentSize()
    }

    override var isEnabled: Bool { didSet { alphaValue = isEnabled ? 1 : 0.4; refreshAppearance(animated: true) } }

    override var intrinsicContentSize: NSSize {
        if label.isEmpty { return NSSize(width: pillHeight, height: pillHeight) }
        let base = super.intrinsicContentSize
        let padding: CGFloat = style == .text ? 12 : (pillHeight >= 34 ? 32 : 26)
        return NSSize(width: ceil(base.width) + padding, height: pillHeight)
    }

    private var palette: (bg: NSColor, hover: NSColor, pressed: NSColor, fg: NSColor, fgHover: NSColor) {
        switch style {
        case .primary: return (CMColor.accent, CMColor.accentHover, CMColor.accentPressed, .white, .white)
        case .secondary: return (CMColor.fill07, CMColor.fill11, CMColor.fill20, .white, .white)
        case .destructive: return (CMColor.negative, CMColor.negativeHover, CMColor.negativePressed, .white, .white)
        case .plain: return (restingFill ?? .clear, restingFill ?? CMColor.fill07, CMColor.fill11, tint ?? CMColor.textMuted, hoverTint ?? tint ?? CMColor.text)
        case .text: return (.clear, .clear, .clear, tint ?? CMColor.textMuted, CMColor.text)
        case .overlay: return (NSColor(white: 0, alpha: 0.6), NSColor(white: 0, alpha: 0.78), NSColor(white: 0, alpha: 0.9), .white, .white)
        }
    }

    private func refreshAppearance(animated: Bool) {
        let colors = palette
        let active = isEnabled
        let background = pressed && active ? colors.pressed : (hovering && active ? colors.hover : colors.bg)
        let foreground = (hovering || pressed) && active ? colors.fgHover : colors.fg
        if animated { CMMotion.animate(layer, to: background.cgColor) } else { layer?.backgroundColor = background.cgColor }
        contentTintColor = foreground
        if !label.isEmpty {
            attributedTitle = NSAttributedString(string: label, attributes: [
                .font: CMFont.semibold(pillHeight >= 34 ? 13 : 12), .foregroundColor: foreground,
            ])
        }
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let hoverArea { removeTrackingArea(hoverArea) }
        let area = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeInActiveApp, .inVisibleRect], owner: self, userInfo: nil)
        addTrackingArea(area)
        hoverArea = area
    }
    override func mouseEntered(with event: NSEvent) { hovering = true; refreshAppearance(animated: true) }
    override func mouseExited(with event: NSEvent) { hovering = false; refreshAppearance(animated: true) }

    override func mouseDown(with event: NSEvent) {
        guard isEnabled else { return }
        pressed = true
        refreshAppearance(animated: true)
        CMMotion.press(self, down: true)
        super.mouseDown(with: event)
        release()
    }

    private func release() {
        if let window { hovering = bounds.contains(convert(window.mouseLocationOutsideOfEventStream, from: nil)) }
        guard pressed else { refreshAppearance(animated: true); return }
        pressed = false
        refreshAppearance(animated: true)
        CMMotion.press(self, down: false)
    }

    @objc private func fire() {
        release()
        handler?()
        release()
    }
}

// MARK: - Toggle

final class CMToggle: NSControl {
    var onChange: ((Bool) -> Void)?
    private(set) var isOn = false
    private let track = CALayer()
    private let knob = CALayer()

    override init(frame frameRect: NSRect) {
        super.init(frame: NSRect(x: 0, y: 0, width: 40, height: 24))
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        track.cornerRadius = 12
        knob.cornerRadius = 10
        knob.backgroundColor = NSColor.white.cgColor
        knob.shadowColor = NSColor.black.cgColor
        knob.shadowOpacity = 0.28
        knob.shadowRadius = 2
        knob.shadowOffset = CGSize(width: 0, height: -1)
        layer?.addSublayer(track)
        track.addSublayer(knob)
        NSLayoutConstraint.activate([widthAnchor.constraint(equalToConstant: 40), heightAnchor.constraint(equalToConstant: 24)])
        setAccessibilityElement(true)
        setAccessibilityRole(.checkBox)
        apply(animated: false)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override var intrinsicContentSize: NSSize { NSSize(width: 40, height: 24) }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func layout() { super.layout(); apply(animated: false) }

    func setOn(_ on: Bool, animated: Bool) {
        guard on != isOn else { return }
        isOn = on
        apply(animated: animated)
    }

    private func apply(animated: Bool) {
        let color = (isOn ? CMColor.accent : CMColor.toggleOff).cgColor
        let fromPosition = (knob.presentation() ?? knob).position
        let fromColor = (track.presentation() ?? track).backgroundColor
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        track.frame = bounds
        knob.frame = CGRect(x: isOn ? bounds.width - 22 : 2, y: 2, width: 20, height: 20)
        track.backgroundColor = color
        CATransaction.commit()
        setAccessibilityValue(isOn ? 1 : 0)
        guard animated, window != nil else { return }
        knob.add(CMMotion.spring("position", from: NSValue(point: fromPosition), to: NSValue(point: knob.position), damping: 0.8, stiffness: 600), forKey: "slide")
        track.add(CMMotion.basic("backgroundColor", from: fromColor, to: color, duration: 0.16), forKey: "color")
    }

    override func mouseDown(with event: NSEvent) {}
    override func mouseUp(with event: NSEvent) {
        guard isEnabled, bounds.contains(convert(event.locationInWindow, from: nil)) else { return }
        isOn.toggle()
        apply(animated: true)
        CATransaction.flush()
        onChange?(isOn)
        if let action { sendAction(action, to: target) }
    }
    override func accessibilityPerformPress() -> Bool {
        isOn.toggle(); apply(animated: true); onChange?(isOn); return true
    }
}

// MARK: - Card, avatar, badge, status pill, progress

final class CMCard: CMBox {
    let stack = NSStackView()
    private let padding: CGFloat
    var onClick: (() -> Void)? { didSet { tracksHover = onClick != nil } }

    init(padding: CGFloat = 18, spacing: CGFloat = 12, fill: NSColor = CMColor.surface) {
        self.padding = padding
        super.init(fill: fill, radius: 20, border: CMColor.line)
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = spacing
        stack.edgeInsets = NSEdgeInsets(top: padding, left: padding, bottom: padding, right: padding)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor), stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.topAnchor.constraint(equalTo: topAnchor), stack.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func add(_ view: NSView, fullWidth: Bool = true, spacingAfter: CGFloat? = nil) {
        stack.addArrangedSubview(view)
        if fullWidth { view.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -2 * padding).isActive = true }
        if let spacingAfter { stack.setCustomSpacing(spacingAfter, after: view) }
    }

    override func hoverChanged() {
        guard onClick != nil else { return }
        CMMotion.animate(layer, key: "borderColor", to: (isHovering ? CMColor.fill20 : CMColor.line).cgColor)
    }
    override func hitTest(_ point: NSPoint) -> NSView? {
        let hit = super.hitTest(point)
        guard onClick != nil, let hit else { return hit }
        return hit is NSButton ? hit : self
    }
    override func mouseDown(with event: NSEvent) {
        guard onClick != nil else { super.mouseDown(with: event); return }
    }
    override func mouseUp(with event: NSEvent) {
        guard let onClick, bounds.contains(convert(event.locationInWindow, from: nil)) else { super.mouseUp(with: event); return }
        onClick()
        resyncHover()
    }
}

final class CMAvatar: CMBox {
    private let icon = NSImageView()
    private let dot = CMBox(fill: CMColor.positive, radius: 5, border: nil)
    private var symbol = ""

    init(symbol: String = "laptopcomputer", size: CGFloat = 34) {
        super.init(fill: CMColor.fill07, radius: size / 2)
        icon.translatesAutoresizingMaskIntoConstraints = false
        icon.contentTintColor = CMColor.textSoft
        addSubview(icon)
        dot.layer?.borderWidth = 2
        dot.layer?.borderColor = CMColor.surface.cgColor
        dot.isHidden = true
        addSubview(dot)
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: size), heightAnchor.constraint(equalToConstant: size),
            icon.centerXAnchor.constraint(equalTo: centerXAnchor), icon.centerYAnchor.constraint(equalTo: centerYAnchor),
            dot.widthAnchor.constraint(equalToConstant: 10), dot.heightAnchor.constraint(equalToConstant: 10),
            dot.trailingAnchor.constraint(equalTo: trailingAnchor, constant: 1), dot.bottomAnchor.constraint(equalTo: bottomAnchor, constant: 1),
        ])
        layer?.masksToBounds = false
        setSymbol(symbol)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func setSymbol(_ name: String) {
        guard name != symbol else { return }
        symbol = name
        icon.image = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: 14, weight: .medium))
    }
    var online = false { didSet { dot.isHidden = !online } }
}

final class CMBadge: CMBox {
    private let label = cmLabel("", CMFont.semibold(11), CMColor.textSoft)
    init(_ text: String = "") {
        super.init(fill: CMColor.fill07, radius: 10)
        addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 9), label.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -9),
            label.topAnchor.constraint(equalTo: topAnchor, constant: 3), label.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -3),
        ])
        label.setContentCompressionResistancePriority(.required, for: .horizontal)
        set(text)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    func set(_ text: String) { label.stringValue = text; isHidden = text.isEmpty }
}

final class CMStatusPill: CMBox {
    private let dot = CMBox(fill: CMColor.textMuted, radius: 3.5)
    private let label = cmLabel("", CMFont.medium(12), CMColor.textSoft)
    private var current = ""

    init() {
        super.init(fill: CMColor.fill07, radius: 14)
        let row = cmHStack([dot, label], spacing: 7)
        addSubview(row)
        label.setContentCompressionResistancePriority(.required, for: .horizontal)
        NSLayoutConstraint.activate([
            dot.widthAnchor.constraint(equalToConstant: 7), dot.heightAnchor.constraint(equalToConstant: 7),
            heightAnchor.constraint(equalToConstant: 28),
            row.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12), row.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            row.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func set(_ text: String, color: NSColor, pulse: Bool = false) {
        let animated = window != nil && current != text
        current = text
        label.stringValue = text
        if animated {
            CMMotion.animate(dot.layer, to: color.cgColor)
            CMMotion.animate(layer, to: color.withAlphaComponent(0.14).cgColor)
        } else {
            dot.layer?.backgroundColor = color.cgColor
            layer?.backgroundColor = color.withAlphaComponent(0.14).cgColor
        }
        CMMotion.pulse(dot.layer, enabled: pulse)
    }
}

final class CMProgressBar: NSView {
    private let fill = CALayer()
    private(set) var value: Double = 0

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        layer?.backgroundColor = CMColor.fill07.cgColor
        layer?.cornerRadius = 2
        fill.backgroundColor = CMColor.accent.cgColor
        fill.cornerRadius = 2
        layer?.addSublayer(fill)
        heightConstraint = heightAnchor.constraint(equalToConstant: 4)
        heightConstraint?.isActive = true
    }
    private var heightConstraint: NSLayoutConstraint?
    func setThickness(_ value: CGFloat) {
        heightConstraint?.constant = value
        layer?.cornerRadius = value / 2
        fill.cornerRadius = value / 2
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    var color: NSColor = CMColor.accent { didSet { fill.backgroundColor = color.cgColor } }

    func set(_ newValue: Double, animated: Bool) {
        value = min(1, max(0, newValue))
        CATransaction.begin()
        if animated && window != nil {
            CATransaction.setAnimationDuration(0.22)
            CATransaction.setAnimationTimingFunction(CMMotion.ease)
        } else {
            CATransaction.setDisableActions(true)
        }
        fill.frame = CGRect(x: 0, y: 0, width: bounds.width * CGFloat(value), height: bounds.height)
        CATransaction.commit()
    }
    override func layout() { super.layout(); set(value, animated: false) }
}

/// 30×30 determinate ring (2.5pt, accent on Fill07) that can morph into a green check.
final class CMProgressRing: NSView {
    private let track = CAShapeLayer()
    private let arc = CAShapeLayer()
    private let check = NSImageView()
    private(set) var value: Double = 0
    private(set) var isDone = false

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        for shape in [track, arc] {
            shape.fillColor = NSColor.clear.cgColor
            shape.lineWidth = 2.5
            shape.lineCap = .round
            layer?.addSublayer(shape)
        }
        track.strokeColor = CMColor.fill07.cgColor
        arc.strokeColor = CMColor.accent.cgColor
        arc.strokeEnd = 0
        check.image = NSImage(systemSymbolName: "checkmark.circle.fill", accessibilityDescription: "Sent")?.withSymbolConfiguration(.init(pointSize: 22, weight: .semibold))
        check.contentTintColor = CMColor.positive
        check.translatesAutoresizingMaskIntoConstraints = false
        check.wantsLayer = true
        check.isHidden = true
        addSubview(check)
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 30), heightAnchor.constraint(equalToConstant: 30),
            check.centerXAnchor.constraint(equalTo: centerXAnchor), check.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override func layout() {
        super.layout()
        let inset: CGFloat = 2.5
        let rect = bounds.insetBy(dx: inset, dy: inset)
        let path = CGMutablePath()
        let center = CGPoint(x: rect.midX, y: rect.midY)
        // Start at 12 o'clock and run clockwise in the (non-flipped) layer space.
        path.addArc(center: center, radius: rect.width / 2, startAngle: .pi / 2, endAngle: .pi / 2 - 2 * .pi, clockwise: true)
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        track.frame = bounds
        arc.frame = bounds
        track.path = path
        arc.path = path
        CATransaction.commit()
    }

    func reset() {
        isDone = false
        value = 0
        check.isHidden = true
        track.isHidden = false
        arc.isHidden = false
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        arc.strokeEnd = 0
        CATransaction.commit()
    }

    func set(_ newValue: Double, animated: Bool) {
        if isDone { reset() }
        let target = CGFloat(min(1, max(0, newValue)))
        let from = (arc.presentation() ?? arc).strokeEnd
        value = Double(target)
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        arc.strokeEnd = target
        CATransaction.commit()
        if animated && window != nil { arc.add(CMMotion.basic("strokeEnd", from: from, to: target, duration: 0.22), forKey: "progress") }
    }

    func showDone(animated: Bool) {
        guard !isDone else { return }
        isDone = true
        track.isHidden = true
        arc.isHidden = true
        check.isHidden = false
        guard animated, let layer = check.layer else { return }
        check.layoutSubtreeIfNeeded()
        layer.add(CMMotion.basic("opacity", from: 0, to: 1, duration: 0.18), forKey: "fade")
        if !CMMotion.reduce {
            let start = CMMotion.centered(CATransform3DMakeScale(0.4, 0.4, 1), layer: layer)
            layer.add(CMMotion.spring("transform", from: NSValue(caTransform3D: start), to: NSValue(caTransform3D: CATransform3DIdentity), damping: 0.6, stiffness: 420), forKey: "pop")
        }
    }
}

/// Muted single-line placeholder row, optionally with a softly pulsing dot.
final class CMEmptyRow: NSView {
    private let dot = CMBox(fill: CMColor.accent, radius: 3)
    private let label = cmLabel("", CMFont.regular(13), CMColor.textMuted)
    init(_ text: String, pulsing: Bool) {
        super.init(frame: .zero)
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        let row = cmHStack([dot, label], spacing: 9)
        addSubview(row)
        NSLayoutConstraint.activate([
            dot.widthAnchor.constraint(equalToConstant: 6), dot.heightAnchor.constraint(equalToConstant: 6),
            row.leadingAnchor.constraint(equalTo: leadingAnchor), row.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor),
            row.topAnchor.constraint(equalTo: topAnchor, constant: 10), row.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -10),
        ])
        set(text, pulsing: pulsing)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    func set(_ text: String, pulsing: Bool) {
        label.stringValue = text
        dot.isHidden = !pulsing
        CMMotion.pulse(dot.layer, enabled: window != nil && pulsing)
    }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        CMMotion.pulse(dot.layer, enabled: window != nil && !dot.isHidden)
    }
}

// MARK: - Animated lists

/// Diffs keyed rows into a stack view: unchanged rows are updated in place (hover
/// and press state survive refresh ticks), new rows fade/grow in, removed rows
/// fade and collapse.
enum CMList {
    private static var leaving = Set<ObjectIdentifier>()
    private static var visibility: [ObjectIdentifier: Int] = [:]

    static func key(of view: NSView) -> String { view.identifier?.rawValue ?? "" }
    static func isLeaving(_ view: NSView) -> Bool { leaving.contains(ObjectIdentifier(view)) }

    static func reconcile<T>(_ stack: NSStackView, _ items: [T], key: (T) -> String, animated: Bool,
                             make: (T) -> NSView, update: (NSView, T) -> Void) {
        let animate = animated && stack.window?.isVisible == true
        let live = stack.arrangedSubviews.filter { !leaving.contains(ObjectIdentifier($0)) }
        var byKey: [String: NSView] = [:]
        for view in live { byKey[Self.key(of: view)] = view }
        let wanted = Set(items.map(key))
        for view in live where !wanted.contains(Self.key(of: view)) { remove(view, from: stack, animated: animate) }

        var previous: NSView?
        for item in items {
            let itemKey = key(item)
            let desired = previous.flatMap { stack.arrangedSubviews.firstIndex(of: $0) }.map { $0 + 1 } ?? 0
            if let existing = byKey[itemKey] {
                update(existing, item)
                if let current = stack.arrangedSubviews.firstIndex(of: existing), current != desired {
                    stack.removeArrangedSubview(existing)
                    let target = previous.flatMap { stack.arrangedSubviews.firstIndex(of: $0) }.map { $0 + 1 } ?? 0
                    stack.insertArrangedSubview(existing, at: min(target, stack.arrangedSubviews.count))
                }
                previous = existing
                continue
            }
            let view = make(item)
            view.identifier = NSUserInterfaceItemIdentifier(itemKey)
            view.translatesAutoresizingMaskIntoConstraints = false
            stack.insertArrangedSubview(view, at: min(desired, stack.arrangedSubviews.count))
            if stack.orientation == .vertical {
                view.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -(stack.edgeInsets.left + stack.edgeInsets.right)).isActive = true
            }
            if animate { reveal(view) }
            previous = view
        }
    }

    private static func layoutRoot(_ view: NSView) { view.window?.contentView?.layoutSubtreeIfNeeded() }

    private static func reveal(_ view: NSView) {
        view.alphaValue = 0
        view.isHidden = true
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.2
            context.timingFunction = CMMotion.ease
            context.allowsImplicitAnimation = !CMMotion.reduce
            view.isHidden = false
            view.animator().alphaValue = 1
            layoutRoot(view)
        }
    }

    static func remove(_ view: NSView, from stack: NSStackView, animated: Bool) {
        guard animated else {
            stack.removeArrangedSubview(view)
            view.removeFromSuperview()
            return
        }
        let id = ObjectIdentifier(view)
        leaving.insert(id)
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.12
            context.timingFunction = CMMotion.ease
            view.animator().alphaValue = 0
        }, completionHandler: {
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = 0.18
                context.timingFunction = CMMotion.ease
                context.allowsImplicitAnimation = !CMMotion.reduce
                view.isHidden = true
                layoutRoot(view)
            }, completionHandler: {
                stack.removeArrangedSubview(view)
                view.removeFromSuperview()
                leaving.remove(id)
            })
        })
    }

    /// Shows/hides an arranged subview with fade + height collapse.
    static func setVisible(_ view: NSView, _ visible: Bool, animated: Bool) {
        let id = ObjectIdentifier(view)
        let generation = (visibility[id] ?? 0) + 1
        visibility[id] = generation
        let animate = animated && view.window?.isVisible == true
        if visible {
            guard view.isHidden || view.alphaValue < 1 else { return }
            guard animate else { view.isHidden = false; view.alphaValue = 1; return }
            if view.isHidden { view.alphaValue = 0 }
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.22
                context.timingFunction = CMMotion.ease
                context.allowsImplicitAnimation = !CMMotion.reduce
                view.isHidden = false
                view.animator().alphaValue = 1
                layoutRoot(view)
            }
        } else {
            guard !view.isHidden else { return }
            guard animate else { view.isHidden = true; view.alphaValue = 1; return }
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = 0.12
                context.timingFunction = CMMotion.ease
                view.animator().alphaValue = 0
            }, completionHandler: {
                guard visibility[id] == generation else { return }
                NSAnimationContext.runAnimationGroup({ context in
                    context.duration = 0.18
                    context.timingFunction = CMMotion.ease
                    context.allowsImplicitAnimation = !CMMotion.reduce
                    view.isHidden = true
                    layoutRoot(view)
                }, completionHandler: {
                    if visibility[id] == generation { view.alphaValue = 1; visibility[id] = nil }
                })
            })
        }
    }
}

// MARK: - Toast

enum CMToast {
    enum Kind { case info, success, error }
    private static weak var current: NSView?

    static func show(_ text: String, kind: Kind = .info, in host: NSView?, duration: TimeInterval? = nil) {
        guard let host, !text.isEmpty else { return }
        if let current { dismiss(current) }
        let pill = CMBox(fill: CMColor.surface, radius: 18, border: CMColor.line)
        var views: [NSView] = []
        switch kind {
        case .success: views.append(cmSymbol("checkmark.circle.fill", size: 14, weight: .semibold, color: CMColor.positive))
        case .error: views.append(cmSymbol("exclamationmark.circle.fill", size: 14, weight: .semibold, color: CMColor.negative))
        case .info: break
        }
        let label = cmLabel(text, CMFont.medium(13), CMColor.text, wrap: true)
        label.maximumNumberOfLines = 3
        label.preferredMaxLayoutWidth = 440
        views.append(label)
        let row = cmHStack(views, spacing: 8)
        row.alignment = .firstBaseline
        pill.addSubview(row)
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
        shadow.shadowBlurRadius = 18
        shadow.shadowOffset = NSSize(width: 0, height: -4)
        pill.shadow = shadow
        host.addSubview(pill, positioned: .above, relativeTo: nil)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: pill.leadingAnchor, constant: 16), row.trailingAnchor.constraint(equalTo: pill.trailingAnchor, constant: -16),
            row.topAnchor.constraint(equalTo: pill.topAnchor, constant: 9), row.bottomAnchor.constraint(equalTo: pill.bottomAnchor, constant: -9),
            pill.centerXAnchor.constraint(equalTo: host.centerXAnchor, constant: 100),
            pill.bottomAnchor.constraint(equalTo: host.bottomAnchor, constant: -24),
            pill.widthAnchor.constraint(lessThanOrEqualToConstant: 520),
        ])
        host.layoutSubtreeIfNeeded()
        pill.layer?.cornerRadius = min(18, pill.bounds.height / 2)
        CMMotion.enter(pill, dy: CMMotion.reduce ? 0 : -8, duration: 0.22)
        current = pill
        CMMotion.after(duration ?? (kind == .error ? 5 : 2.4)) { [weak pill] in if let pill { dismiss(pill) } }
    }

    static func dismiss(_ view: NSView) {
        if current === view { current = nil }
        guard view.superview != nil, view.alphaValue > 0 else { return }
        view.layer?.add(CMMotion.basic("opacity", from: 1, to: 0, duration: 0.18), forKey: "exit")
        if !CMMotion.reduce {
            view.layer?.add(CMMotion.basic("transform", from: NSValue(caTransform3D: CATransform3DIdentity), to: NSValue(caTransform3D: CATransform3DMakeTranslation(0, -6, 0)), duration: 0.18), forKey: "exitSlide")
        }
        view.alphaValue = 0
        CMMotion.after(0.2) { view.removeFromSuperview() }
    }
}

// MARK: - Dialog

private final class CMDialogPanel: NSPanel {
    var onCancel: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onCancel?() }
}

enum CMDialog {
    /// The main window: dialogs dim it and float centred above it while it is visible.
    static weak var hostWindow: NSWindow?

    @discardableResult static func run(title: String, message: String, accessory: NSView? = nil, buttons: [String] = ["Done"]) -> Int {
        present(title: title, message: message, accessory: accessory, buttons: buttons)
    }

    static func confirm(title: String, message: String) -> Bool { run(title: title, message: message, buttons: ["Cancel", "Continue"]) == 1 }

    static func confirmDestructive(title: String, message: String, action: String) -> Bool {
        present(title: title, message: message, buttons: ["Cancel", action], destructive: true) == 1
    }

    /// Synchronous, application-modal dialog. Returns the index of the chosen button;
    /// Esc returns 0 and Return chooses the last (primary) button.
    @discardableResult static func present(title: String, message: String, accessory: NSView? = nil, buttons: [String] = ["Done"], width: CGFloat = 440, destructive: Bool = false) -> Int {
        let buttons = buttons.isEmpty ? ["Done"] : buttons
        let inner = width - 48
        let margin: CGFloat = 40

        let card = CMBox(fill: CMColor.surface, radius: 22, border: CMColor.line)
        card.layer?.shadowColor = NSColor.black.cgColor
        card.layer?.shadowOpacity = 0.45
        card.layer?.shadowRadius = 26
        card.layer?.shadowOffset = CGSize(width: 0, height: -10)
        let stack = cmVStack([], spacing: 8)
        stack.edgeInsets = NSEdgeInsets(top: 24, left: 24, bottom: 22, right: 24)
        card.addSubview(stack)

        let heading = cmLabel(title, CMFont.semibold(18), CMColor.text, wrap: true)
        heading.preferredMaxLayoutWidth = inner
        stack.addArrangedSubview(heading)
        heading.widthAnchor.constraint(equalToConstant: inner).isActive = true
        var last: NSView = heading
        if !message.isEmpty {
            let detail = cmLabel(message, CMFont.regular(14), CMColor.textMuted, wrap: true)
            detail.preferredMaxLayoutWidth = inner
            stack.addArrangedSubview(detail)
            detail.widthAnchor.constraint(equalToConstant: inner).isActive = true
            last = detail
        }
        stack.setCustomSpacing(18, after: last)
        var field: NSTextField?
        if let accessory {
            let styled = styledAccessory(accessory, field: &field)
            stack.addArrangedSubview(styled)
            styled.widthAnchor.constraint(equalToConstant: inner).isActive = true
            stack.setCustomSpacing(22, after: styled)
        }

        let actions = cmHStack([cmSpacer()], spacing: 10)
        var primary: CMPillButton?
        for (index, label) in buttons.enumerated() {
            let isPrimary = index == buttons.count - 1
            let style: CMPillButton.Style = isPrimary ? (destructive ? .destructive : .primary) : .secondary
            let button = CMPillButton(label, style: style, height: 36) {
                NSApp.stopModal(withCode: NSApplication.ModalResponse(rawValue: index))
            }
            button.widthAnchor.constraint(greaterThanOrEqualToConstant: 84).isActive = true
            if isPrimary { button.keyEquivalent = "\r"; primary = button }
            else if index == 0 { button.keyEquivalent = "\u{1b}" }
            actions.addArrangedSubview(button)
        }
        stack.addArrangedSubview(actions)
        actions.widthAnchor.constraint(equalToConstant: inner).isActive = true

        let content = NSView()
        content.wantsLayer = true
        content.addSubview(card)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: card.leadingAnchor), stack.trailingAnchor.constraint(equalTo: card.trailingAnchor),
            stack.topAnchor.constraint(equalTo: card.topAnchor), stack.bottomAnchor.constraint(equalTo: card.bottomAnchor),
            card.widthAnchor.constraint(equalToConstant: width),
            card.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: margin), card.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -margin),
            card.topAnchor.constraint(equalTo: content.topAnchor, constant: margin), card.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -margin),
        ])

        let panel = CMDialogPanel(contentRect: NSRect(x: 0, y: 0, width: width + 2 * margin, height: 240), styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.isReleasedWhenClosed = false
        panel.animationBehavior = .none
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.contentView = content
        panel.onCancel = { NSApp.stopModal(withCode: NSApplication.ModalResponse(rawValue: 0)) }
        content.layoutSubtreeIfNeeded()
        panel.setContentSize(content.fittingSize)
        content.layoutSubtreeIfNeeded()

        var dim: NSView?
        let host = hostWindow.flatMap { $0.isVisible && !$0.isMiniaturized ? $0 : nil }
        if let host, let hostContent = host.contentView {
            let frame = host.frame
            let size = panel.frame.size
            panel.setFrameOrigin(NSPoint(x: frame.midX - size.width / 2, y: frame.midY - size.height / 2 + 12))
            let shade = CMBox(fill: .black)
            shade.translatesAutoresizingMaskIntoConstraints = true
            shade.frame = hostContent.bounds
            shade.autoresizingMask = [.width, .height]
            shade.alphaValue = 0.55
            hostContent.addSubview(shade, positioned: .above, relativeTo: nil)
            shade.layer?.add(CMMotion.basic("opacity", from: 0, to: 0.55, duration: 0.26), forKey: "dim")
            host.addChildWindow(panel, ordered: .above)
            dim = shade
        } else {
            panel.level = .modalPanel
            panel.center()
        }

        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        if let field {
            panel.makeFirstResponder(field)
            field.target = primary
            field.action = #selector(NSButton.performClick(_:))
        }
        if let layer = card.layer {
            layer.add(CMMotion.basic("opacity", from: 0, to: 1, duration: 0.26), forKey: "enterOpacity")
            if !CMMotion.reduce {
                let start = CMMotion.centered(CATransform3DMakeScale(0.94, 0.94, 1), layer: layer)
                layer.add(CMMotion.basic("transform", from: NSValue(caTransform3D: start), to: NSValue(caTransform3D: CATransform3DIdentity), duration: 0.26), forKey: "enterScale")
            }
        }

        let response = NSApp.runModal(for: panel)
        panel.makeFirstResponder(nil)

        if let layer = card.layer {
            layer.add(CMMotion.basic("opacity", from: 1, to: 0, duration: 0.18), forKey: "exitOpacity")
            if !CMMotion.reduce {
                let end = CMMotion.centered(CATransform3DMakeScale(0.97, 0.97, 1), layer: layer)
                layer.add(CMMotion.basic("transform", from: NSValue(caTransform3D: CATransform3DIdentity), to: NSValue(caTransform3D: end), duration: 0.18), forKey: "exitScale")
            }
            layer.opacity = 0
        }
        if let dim {
            dim.layer?.add(CMMotion.basic("opacity", from: 0.55, to: 0, duration: 0.18), forKey: "undim")
            dim.alphaValue = 0
        }
        CMMotion.after(0.2) {
            panel.parent?.removeChildWindow(panel)
            panel.orderOut(nil)
            dim?.removeFromSuperview()
        }
        return response.rawValue
    }

    private static func firstEditableField(in view: NSView) -> NSTextField? {
        if let field = view as? NSTextField, field.isEditable { return field }
        for child in view.subviews { if let found = firstEditableField(in: child) { return found } }
        return nil
    }

    /// Plain editable text fields become Ember inputs (Fill06, radius 14, hairline border).
    private static func styledAccessory(_ accessory: NSView, field: inout NSTextField?) -> NSView {
        guard let text = accessory as? NSTextField, text.isEditable else {
            field = firstEditableField(in: accessory)
            return accessory
        }
        field = text
        text.isBordered = false
        text.isBezeled = false
        text.drawsBackground = false
        text.focusRingType = .none
        text.textColor = CMColor.text
        text.translatesAutoresizingMaskIntoConstraints = false
        if text.font == nil || text.font?.pointSize == NSFont.systemFontSize { text.font = CMFont.regular(14) }
        text.cell?.usesSingleLineMode = true
        text.cell?.isScrollable = true
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = text.alignment
        if let placeholder = text.placeholderString, let font = text.font {
            text.placeholderAttributedString = NSAttributedString(string: placeholder, attributes: [
                .foregroundColor: CMColor.textFaint, .font: font, .paragraphStyle: paragraph,
            ])
        }
        let box = CMBox(fill: CMColor.fill06, radius: 14, border: CMColor.accent.withAlphaComponent(0.55))
        box.addSubview(text)
        let height = max(44, ceil(text.intrinsicContentSize.height) + 18)
        NSLayoutConstraint.activate([
            text.leadingAnchor.constraint(equalTo: box.leadingAnchor, constant: 14),
            text.trailingAnchor.constraint(equalTo: box.trailingAnchor, constant: -14),
            text.centerYAnchor.constraint(equalTo: box.centerYAnchor),
            box.heightAnchor.constraint(equalToConstant: height),
        ])
        return box
    }
}

// MARK: - Clipboard reading

enum CMClipboardContent {
    case empty
    case text(String)
    case image(NSImage, format: String, pixelSize: NSSize)
    case imageFile(URL)
    case files([URL])
    case unsupported
}

enum CMThumbs {
    final class Thumb {
        let image: CGImage
        let pixelSize: CGSize
        let format: String
        init(image: CGImage, pixelSize: CGSize, format: String) { self.image = image; self.pixelSize = pixelSize; self.format = format }
        var nsImage: NSImage { NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height)) }
    }

    private static let queue = DispatchQueue(label: "dev.clipmesh.thumbnails", qos: .userInitiated, attributes: .concurrent)
    private static let cache = NSCache<NSString, Thumb>()

    static func isImage(_ url: URL) -> Bool {
        if let type = (try? url.resourceValues(forKeys: [.contentTypeKey]))?.contentType { return type.conforms(to: .image) }
        if let type = UTType(filenameExtension: url.pathExtension) { return type.conforms(to: .image) }
        return false
    }

    static func format(of url: URL) -> String {
        let type = (try? url.resourceValues(forKeys: [.contentTypeKey]))?.contentType ?? UTType(filenameExtension: url.pathExtension)
        return (type?.preferredFilenameExtension ?? url.pathExtension).uppercased()
    }

    static func loadSync(_ url: URL, maxPixel: Int) -> Thumb? {
        let key = "\(url.path)#\(maxPixel)" as NSString
        if let hit = cache.object(forKey: key) { return hit }
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
        var width = (properties?[kCGImagePropertyPixelWidth] as? NSNumber)?.doubleValue ?? 0
        var height = (properties?[kCGImagePropertyPixelHeight] as? NSNumber)?.doubleValue ?? 0
        if let orientation = properties?[kCGImagePropertyOrientation] as? NSNumber, orientation.intValue >= 5 { swap(&width, &height) }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        let thumb = Thumb(image: image, pixelSize: CGSize(width: width > 0 ? width : Double(image.width), height: height > 0 ? height : Double(image.height)), format: format(of: url))
        cache.setObject(thumb, forKey: key)
        return thumb
    }

    static func load(_ url: URL, maxPixel: Int, completion: @escaping (Thumb?) -> Void) {
        if let hit = cache.object(forKey: "\(url.path)#\(maxPixel)" as NSString) { completion(hit); return }
        queue.async {
            let thumb = loadSync(url, maxPixel: maxPixel)
            DispatchQueue.main.async { completion(thumb) }
        }
    }
}

enum CMClipboardReader {
    /// Order matters: Finder copies carry file URLs *and* a generic icon image,
    /// so file URLs win, then bitmap data, then text, then vector images.
    static func read(_ pasteboard: NSPasteboard) -> CMClipboardContent {
        let urls = (pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        if !urls.isEmpty {
            if urls.count == 1, CMThumbs.isImage(urls[0]) { return .imageFile(urls[0]) }
            return .files(urls)
        }
        let types = pasteboard.types ?? []
        let imageTypes = Set(NSImage.imageTypes)
        let vector: Set<String> = [NSPasteboard.PasteboardType.pdf.rawValue, "com.adobe.encapsulated-postscript"]
        if types.contains(where: { imageTypes.contains($0.rawValue) && !vector.contains($0.rawValue) }), let image = NSImage(pasteboard: pasteboard) {
            return .image(image, format: format(for: types), pixelSize: pixelSize(of: image))
        }
        if let text = pasteboard.string(forType: .string), !text.isEmpty { return .text(text) }
        if let html = pasteboard.string(forType: .html) {
            let plain = plainText(fromHTML: html)
            if !plain.isEmpty { return .text(plain) }
        }
        if let rtf = pasteboard.data(forType: .rtf), let attributed = NSAttributedString(rtf: rtf, documentAttributes: nil), !attributed.string.isEmpty {
            return .text(attributed.string)
        }
        if types.contains(where: { imageTypes.contains($0.rawValue) }), let image = NSImage(pasteboard: pasteboard) {
            return .image(image, format: format(for: types), pixelSize: pixelSize(of: image))
        }
        return types.isEmpty ? .empty : .unsupported
    }

    private static func format(for types: [NSPasteboard.PasteboardType]) -> String {
        if types.contains(.png) { return "PNG" }
        if types.contains(where: { $0.rawValue == "public.jpeg" }) { return "JPEG" }
        if types.contains(.tiff) { return "TIFF" }
        if types.contains(.pdf) { return "PDF" }
        return "Image"
    }

    private static func pixelSize(of image: NSImage) -> NSSize {
        if let rep = image.representations.first, rep.pixelsWide > 0, rep.pixelsHigh > 0 {
            return NSSize(width: rep.pixelsWide, height: rep.pixelsHigh)
        }
        return image.size
    }

    static func plainText(fromHTML html: String) -> String {
        var text = html.replacingOccurrences(of: "(?is)<(script|style)[^>]*>.*?</\\1>", with: "", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<br[^>]*>", with: "\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</(p|div|li|h[1-6]|tr)>", with: "\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        for (entity, value) in [("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'"), ("&amp;", "&")] {
            text = text.replacingOccurrences(of: entity, with: value)
        }
        text = text.replacingOccurrences(of: "\n{3,}", with: "\n\n", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

/// Human-readable clipboard summary (used by --clipboard-preview-self-test).
/// It never exposes raw pasteboard type identifiers.
enum CMClipboardSnapshot {
    static func describe(_ pasteboard: NSPasteboard) -> String {
        switch CMClipboardReader.read(pasteboard) {
        case .empty: return "Clipboard is empty."
        case .text(let text): return String(text.prefix(20_000))
        case .image(_, let format, let size): return "Image · \(format) · \(Int(size.width))×\(Int(size.height))"
        case .imageFile(let url): return "Image · \(url.lastPathComponent)"
        case .files(let urls): return "Files\n" + urls.prefix(30).map(\.lastPathComponent).joined(separator: "\n")
        case .unsupported: return "This clipboard content can’t be previewed."
        }
    }
}

// MARK: - Shared files intake (Finder Share extension, Services, drag and drop)

enum CMShareIntake {
    /// Parses clipmesh-share://send?f=<path>&f=<path>… and the legacy ?manifest=<file> form.
    static func files(from url: URL) -> [URL] {
        guard url.scheme == "clipmesh-share", let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return [] }
        var result: [URL] = []
        for item in components.queryItems ?? [] {
            guard let value = item.value, !value.isEmpty else { continue }
            switch item.name {
            case "f":
                result.append(URL(fileURLWithPath: value))
            case "manifest":
                let manifest = URL(fileURLWithPath: value)
                if let contents = try? String(contentsOf: manifest, encoding: .utf8) {
                    result += contents.split(separator: "\n").map { URL(fileURLWithPath: String($0)) }
                }
                if manifest.lastPathComponent.hasPrefix("clipmesh-share-") { try? FileManager.default.removeItem(at: manifest) }
            default:
                continue
            }
        }
        return result
    }

    /// Regular files only; folders expand recursively (hidden items and package
    /// contents skipped); de-duplicated, order preserved.
    static func expand(_ urls: [URL], limit: Int = 5_000) -> [URL] {
        var output: [URL] = []
        var seen = Set<String>()
        func add(_ url: URL) {
            let standard = url.standardizedFileURL
            if seen.insert(standard.path).inserted { output.append(standard) }
        }
        for url in urls where url.isFileURL {
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) else { continue }
            if !isDirectory.boolValue { add(url); continue }
            guard let enumerator = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.isRegularFileKey], options: [.skipsHiddenFiles, .skipsPackageDescendants]) else { continue }
            for case let child as URL in enumerator {
                if (try? child.resourceValues(forKeys: [.isRegularFileKey]))?.isRegularFile == true { add(child) }
                if output.count >= limit { break }
            }
            if output.count >= limit { break }
        }
        return output
    }
}

struct CLIResult {
    let status: Int32
    let output: String
    let error: String
}

struct PeerState {
    let id: String
    let name: String
    let lastSeenMs: UInt64
}

struct UIState {
    let deviceID: String
    let deviceName: String
    let spaceID: String
    let sendEnabled: Bool
    let receiveEnabled: Bool
    let peers: [PeerState]
}

enum Runtime {
    static let fileManager = FileManager.default

    static var executableDirectory: URL {
        if let executable = Bundle.main.executableURL {
            return executable.deletingLastPathComponent()
        }
        return URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
    }

    static var cli: URL { executableDirectory.appendingPathComponent("clipmesh-bin") }

    static var support: URL {
        fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("dev.ClipMesh.ClipMesh", isDirectory: true)
    }

    static var config: URL { support.appendingPathComponent("config.json") }
    static var log: URL { support.appendingPathComponent("clipmesh.log") }
    static var instanceLock: URL { support.appendingPathComponent("mac-ui.lock") }

    static func acquireInstanceLock() throws -> Int32? {
        try fileManager.createDirectory(at: support, withIntermediateDirectories: true)
        let descriptor = Darwin.open(instanceLock.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else {
            throw NSError(domain: "ClipMesh", code: Int(errno), userInfo: [
                NSLocalizedDescriptionKey: "ClipMesh could not create its single-instance lock."
            ])
        }
        guard Darwin.lockf(descriptor, F_TLOCK, 0) == 0 else {
            Darwin.close(descriptor)
            return nil
        }
        return descriptor
    }

    static func releaseInstanceLock(_ descriptor: Int32) {
        guard descriptor >= 0 else { return }
        _ = Darwin.lockf(descriptor, F_ULOCK, 0)
        Darwin.close(descriptor)
    }

    private static func external(_ executable: String, _ arguments: [String]) throws -> CLIResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        process.waitUntilExit()
        return CLIResult(
            status: process.terminationStatus,
            output: String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "",
            error: String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        )
    }

    private static func clipboardPort() -> Int {
        guard
            let data = try? Data(contentsOf: config),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let number = object["tcp_port"] as? NSNumber
        else { return 41474 }
        return number.intValue
    }

    private static func processIsClipMeshDaemon(_ pid: Int32) -> Bool {
        guard let result = try? external("/usr/sbin/lsof", ["-nP", "-a", "-p", String(pid), "-d", "txt", "-FcFn"]), result.status == 0 else { return false }
        let lines = result.output.split(whereSeparator: { $0.isNewline }).map(String.init)
        let commandMatches = lines.contains("cclipmesh-bin")
        let executableMatches = lines.contains { line in
            guard line.first == "n" else { return false }
            return URL(fileURLWithPath: String(line.dropFirst())).lastPathComponent == "clipmesh-bin"
        }
        return commandMatches && executableMatches
    }

    static func clipboardDaemonIsListening(_ pid: Int32) -> Bool {
        guard pid > 0, processIsClipMeshDaemon(pid) else { return false }
        guard let result = try? external(
            "/usr/sbin/lsof",
            ["-nP", "-a", "-p", String(pid), "-iTCP:\(clipboardPort())", "-sTCP:LISTEN", "-t"]
        ), result.status == 0 else { return false }
        return result.output.split(whereSeparator: { $0.isWhitespace }).contains { Int32($0) == pid }
    }

    static func reclaimStaleDaemonListener() throws {
        let port = clipboardPort()
        let result = try external("/usr/sbin/lsof", ["-nP", "-t", "-iTCP:\(port)", "-sTCP:LISTEN"])
        guard result.status == 0 else { return } // lsof uses 1 when no process matches.
        let pids = result.output.split(whereSeparator: { $0.isWhitespace }).compactMap { Int32($0) }
        for pid in Set(pids) where pid != getpid() {
            guard processIsClipMeshDaemon(pid) else {
                throw NSError(domain: "ClipMesh", code: 48, userInfo: [
                    NSLocalizedDescriptionKey: "Clipboard port \(port) is already used by another application. ClipMesh left that process untouched."
                ])
            }
            guard Darwin.kill(pid, SIGTERM) == 0 || errno == ESRCH else {
                throw NSError(domain: "ClipMesh", code: Int(errno), userInfo: [
                    NSLocalizedDescriptionKey: "ClipMesh found its previous background process but could not stop it."
                ])
            }
            for _ in 0..<20 {
                if Darwin.kill(pid, 0) != 0 && errno == ESRCH { break }
                usleep(100_000)
            }
            if Darwin.kill(pid, 0) == 0 {
                // The identity was verified immediately before SIGTERM. A hard stop
                // is safe here and prevents a crashed old build blocking every launch.
                _ = Darwin.kill(pid, SIGKILL)
                for _ in 0..<10 {
                    if Darwin.kill(pid, 0) != 0 && errno == ESRCH { break }
                    usleep(100_000)
                }
            }
            guard Darwin.kill(pid, 0) != 0 && errno == ESRCH else {
                throw NSError(domain: "ClipMesh", code: 48, userInfo: [
                    NSLocalizedDescriptionKey: "The previous ClipMesh background process did not stop."
                ])
            }
        }
    }

    static func run(_ arguments: [String]) throws -> CLIResult {
        let process = Process()
        process.executableURL = cli
        process.arguments = arguments
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        process.waitUntilExit()
        return CLIResult(
            status: process.terminationStatus,
            output: String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "",
            error: String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        )
    }

    static func checked(_ arguments: [String], message: String) throws -> String {
        let result = try run(arguments)
        guard result.status == 0 else {
            let detail = result.error.isEmpty ? result.output : result.error
            throw NSError(domain: "ClipMesh", code: Int(result.status), userInfo: [
                NSLocalizedDescriptionKey: "\(message)\n\(detail)"
            ])
        }
        return result.output.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func deviceName() -> String {
        let candidate = Host.current().localizedName ?? ProcessInfo.processInfo.hostName
        let value = candidate.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "Mac" : value
    }

    static func initialize() throws {
        _ = try checked(["init", "--name", deviceName()], message: "Could not initialize ClipMesh.")
    }

    static func verifyReady() throws {
        _ = try checked(["status"], message: "ClipMesh configuration exists, but its encryption key could not be loaded.")
    }

    static func prepareFirstRun() throws {
        try fileManager.createDirectory(at: support, withIntermediateDirectories: true)

        if fileManager.fileExists(atPath: config.path) {
            let status = try run(["status"])
            if status.status == 0 { return }

            let detail = status.error + "\n" + status.output
            let missingKey = detail.localizedCaseInsensitiveContains("No matching entry found in secure storage") ||
                detail.localizedCaseInsensitiveContains("read space key from OS keyring")

            guard missingKey else {
                throw NSError(domain: "ClipMesh", code: Int(status.status), userInfo: [
                    NSLocalizedDescriptionKey: "ClipMesh could not read its existing configuration.\n\(detail)"
                ])
            }

            let stamp = Int(Date().timeIntervalSince1970)
            let backup = support.appendingPathComponent("config.unrecoverable-v0.1.1-\(stamp).bak")
            try fileManager.moveItem(at: config, to: backup)
        }

        try initialize()
        try verifyReady()
    }

    static func pairingLink() throws -> String {
        try checked(["pairing-uri"], message: "Could not create the pairing code.")
    }

    static func forgetPeer(_ id: String) throws {
        _ = try checked(["forget-peer", id], message: "Could not remove this paired device.")
    }

    static func seedPeer(_ id: String, name: String) throws {
        _ = try checked(["seed-peer", id, "--name", name], message: "Could not save the paired device.")
    }

    static func setName(_ name: String) throws {
        _ = try checked(["set-name", "--name", name], message: "Could not rename this device.")
    }

    static func setSync(send: Bool, receive: Bool) throws {
        _ = try checked([
            "set-sync", "--send", send ? "true" : "false",
            "--receive", receive ? "true" : "false"
        ], message: "Could not save sync settings.")
    }

    static func join(_ uri: String, name: String) throws {
        _ = try checked(["join", uri, "--name", name, "--replace"], message: "Could not join that ClipMesh space.")
    }

    static func createNewSpace(name: String) throws {
        _ = try checked(["new-space", "--name", name], message: "Could not create a new ClipMesh space.")
    }

    static func resetIdentity(name: String) throws {
        _ = try checked(["reset", "--name", name], message: "Could not reset ClipMesh pairing.")
    }

    static func uiState() throws -> UIState {
        let output = try checked(["ui-state"], message: "Could not read ClipMesh state.")
        var deviceID = ""
        var deviceName = "Mac"
        var spaceID = ""
        var send = true
        var receive = true
        var peers: [PeerState] = []

        for line in output.split(whereSeparator: { $0.isNewline }) {
            let parts = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard let kind = parts.first else { continue }
            switch kind {
            case "DEVICE" where parts.count >= 3:
                deviceID = parts[1]
                deviceName = parts[2]
            case "SPACE" where parts.count >= 2:
                spaceID = parts[1]
            case "SYNC" where parts.count >= 3:
                send = parts[1].lowercased() == "true"
                receive = parts[2].lowercased() == "true"
            case "PEER" where parts.count >= 4:
                peers.append(PeerState(id: parts[1], name: parts[3], lastSeenMs: UInt64(parts[2]) ?? 0))
            default:
                continue
            }
        }

        guard !deviceID.isEmpty, !spaceID.isEmpty else {
            throw NSError(domain: "ClipMesh", code: 1, userInfo: [NSLocalizedDescriptionKey: "ClipMesh returned incomplete device state."])
        }
        return UIState(deviceID: deviceID, deviceName: deviceName, spaceID: spaceID, sendEnabled: send, receiveEnabled: receive, peers: peers)
    }
}

let clipMeshDevArgs = CommandLine.arguments
if clipMeshDevArgs.contains("--dev-test-transfer-fingerprint") {
    print(LocalTransferManager.shared.devTestFingerprint())
    exit(0)
}
if let index = clipMeshDevArgs.firstIndex(of: "--dev-test-favorite"), clipMeshDevArgs.count > index + 1 {
    let fingerprint = clipMeshDevArgs[index + 1]
    LocalTransferManager.shared.setFavorite(fingerprint, true)
    print("favorited \(fingerprint)")
    exit(0)
}
if let index = clipMeshDevArgs.firstIndex(of: "--dev-test-send-file"), clipMeshDevArgs.count > index + 3 {
    do {
        try LocalTransferManager.shared.devTestSend(
            file: URL(fileURLWithPath: clipMeshDevArgs[index + 1]),
            address: clipMeshDevArgs[index + 2],
            fingerprint: clipMeshDevArgs[index + 3]
        )
        print("ClipMesh macOS physical file send: PASS")
        exit(0)
    } catch {
        fputs("ClipMesh macOS physical file send failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

if CommandLine.arguments.contains("--smoke-test") {
    do {
        try Runtime.prepareFirstRun()
        try Runtime.verifyReady()
        _ = try Runtime.uiState()
        try TransferSelfTest.run()
        print("ClipMesh native macOS first-run + transfer UI smoke test passed")
        exit(0)
    } catch {
        fputs("ClipMesh smoke test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

if CommandLine.arguments.contains("--clipboard-preview-self-test") {
    let pasteboard = NSPasteboard(name: NSPasteboard.Name("dev.clipmesh.preview-self-test"))
    pasteboard.clearContents()
    pasteboard.setString("ClipMesh clipboard self-test", forType: .string)
    let snapshot = CMClipboardSnapshot.describe(pasteboard)
    guard snapshot.contains("ClipMesh clipboard self-test") else {
        fputs("ClipMesh clipboard preview self-test failed\n", stderr)
        exit(1)
    }
    print("ClipMesh clipboard preview self-test passed")
    exit(0)
}

if CommandLine.arguments.contains("--reclaim-stale-daemon-test") {
    do {
        try Runtime.reclaimStaleDaemonListener()
        print("ClipMesh stale-daemon ownership test passed")
        exit(0)
    } catch {
        fputs("ClipMesh stale-daemon ownership test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

// MARK: - Window chrome

/// Window background (with a soft top-left glow) and the whole-window file drop target.
private final class CMRootView: NSView {
    var onFiles: (([URL]) -> Void)?
    private let overlay = CMDropOverlay()

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        registerForDraggedTypes([.fileURL])
        overlay.isHidden = true
        overlay.translatesAutoresizingMaskIntoConstraints = true
        overlay.autoresizingMask = [.width, .height]
        addSubview(overlay)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override var isOpaque: Bool { true }
    override func setFrameSize(_ newSize: NSSize) { super.setFrameSize(newSize); needsDisplay = true }

    override func draw(_ dirtyRect: NSRect) {
        CMColor.background.setFill()
        bounds.fill()
        let center = NSPoint(x: bounds.minX + 60, y: bounds.maxY - 40)
        NSGradient(colors: [CMColor.glow, CMColor.glow.withAlphaComponent(0)])?
            .draw(fromCenter: center, radius: 0, toCenter: center, radius: max(bounds.width, bounds.height) * 0.6, options: [])
    }

    private func fileURLs(_ info: NSDraggingInfo) -> [URL] {
        (info.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
    }

    private func setOverlay(_ visible: Bool) {
        guard overlay.isHidden == visible else { return }
        overlay.frame = bounds
        if visible {
            addSubview(overlay, positioned: .above, relativeTo: nil)
            overlay.isHidden = false
            CMMotion.enter(overlay, duration: 0.16)
        } else {
            overlay.isHidden = true
        }
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        guard !fileURLs(sender).isEmpty else { return [] }
        setOverlay(true)
        return .copy
    }
    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation { overlay.isHidden ? [] : .copy }
    override func draggingExited(_ sender: NSDraggingInfo?) { setOverlay(false) }
    override func draggingEnded(_ sender: NSDraggingInfo) { setOverlay(false) }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        setOverlay(false)
        let urls = fileURLs(sender)
        guard !urls.isEmpty else { return false }
        onFiles?(urls)
        return true
    }
}

private final class CMDropOverlay: NSView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        let icon = cmSymbol("arrow.down.doc", size: 30, weight: .medium, color: CMColor.accent)
        let title = cmLabel("Drop to send", CMFont.semibold(18))
        let caption = cmLabel("Files are added to Transfer", CMFont.regular(13), CMColor.textMuted)
        let stack = cmVStack([icon, title, caption], spacing: 8)
        stack.alignment = .centerX
        stack.setCustomSpacing(14, after: icon)
        addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: centerXAnchor), stack.centerYAnchor.constraint(equalTo: centerYAnchor)])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func draw(_ dirtyRect: NSRect) {
        CMColor.background.withAlphaComponent(0.86).setFill()
        bounds.fill()
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 14, dy: 14), xRadius: 22, yRadius: 22)
        CMColor.accentSoft.setFill()
        path.fill()
        path.lineWidth = 2
        path.setLineDash([9, 7], count: 2, phase: 0)
        CMColor.accent.setStroke()
        path.stroke()
    }
}

private final class CMNavItem: CMHoverView {
    var onClick: (() -> Void)?
    var isSelected = false { didSet { if oldValue != isSelected { refresh(animated: true) } } }
    private let icon = NSImageView()
    private let label: NSTextField

    init(title: String, symbol: String) {
        label = cmLabel(title, CMFont.medium(14), CMColor.textMuted)
        super.init(frame: .zero)
        wantsLayer = true
        tracksHover = true
        layer?.cornerRadius = 22
        icon.image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)?.withSymbolConfiguration(.init(pointSize: 15, weight: .medium))
        icon.translatesAutoresizingMaskIntoConstraints = false
        addSubview(icon)
        addSubview(label)
        NSLayoutConstraint.activate([
            icon.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16), icon.centerYAnchor.constraint(equalTo: centerYAnchor),
            icon.widthAnchor.constraint(equalToConstant: 20),
            label.leadingAnchor.constraint(equalTo: icon.trailingAnchor, constant: 11), label.centerYAnchor.constraint(equalTo: centerYAnchor),
            label.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -12),
        ])
        setAccessibilityElement(true)
        setAccessibilityRole(.button)
        setAccessibilityLabel(title)
        refresh(animated: false)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    private func refresh(animated: Bool) {
        let foreground = isSelected ? CMColor.text : (isHovering ? CMColor.textSoft : CMColor.textMuted)
        icon.contentTintColor = foreground
        label.textColor = foreground
        let background = (!isSelected && isHovering) ? CMColor.fill05 : NSColor.clear
        if animated { CMMotion.animate(layer, to: background.cgColor) } else { layer?.backgroundColor = background.cgColor }
    }
    override func hoverChanged() { refresh(animated: true) }
    override func mouseDown(with event: NSEvent) { CMMotion.press(self, down: true) }
    override func mouseUp(with event: NSEvent) {
        CMMotion.press(self, down: false)
        if bounds.contains(convert(event.locationInWindow, from: nil)) { onClick?() }
    }
    override func accessibilityPerformPress() -> Bool { onClick?(); return true }
}

/// Navigation items with ONE accent pill that springs between them.
private final class CMNavList: NSView {
    var onSelect: ((Int) -> Void)?
    private(set) var selected = 0
    private var items: [CMNavItem] = []
    private let pillHost = NSView()
    private let pill = CALayer()
    private let itemHeight: CGFloat = 44
    private let gap: CGFloat = 4

    override var isFlipped: Bool { true }

    init(items specs: [(String, String)]) {
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        wantsLayer = true
        pillHost.wantsLayer = true
        addSubview(pillHost)
        pill.backgroundColor = CMColor.accent.cgColor
        pill.cornerRadius = itemHeight / 2
        pillHost.layer?.addSublayer(pill)
        for (index, spec) in specs.enumerated() {
            let item = CMNavItem(title: spec.0, symbol: spec.1)
            item.onClick = { [weak self] in self?.select(index, animated: true, notify: true) }
            addSubview(item)
            items.append(item)
        }
        items.first?.isSelected = true
        heightAnchor.constraint(equalToConstant: CGFloat(specs.count) * itemHeight + CGFloat(max(0, specs.count - 1)) * gap).isActive = true
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    private func pillFrame(_ index: Int) -> CGRect {
        guard items.indices.contains(index) else { return .zero }
        return pillHost.convert(items[index].frame, from: self)
    }

    override func layout() {
        super.layout()
        pillHost.frame = bounds
        for (index, item) in items.enumerated() {
            item.frame = NSRect(x: 0, y: CGFloat(index) * (itemHeight + gap), width: bounds.width, height: itemHeight)
        }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        pill.frame = pillFrame(selected)
        CATransaction.commit()
    }

    func select(_ index: Int, animated: Bool, notify: Bool = false) {
        guard items.indices.contains(index) else { return }
        let previous = selected
        selected = index
        for (i, item) in items.enumerated() { item.isSelected = i == index }
        if previous != index {
            let from = (pill.presentation() ?? pill).position
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            pill.frame = pillFrame(index)
            CATransaction.commit()
            if animated && window != nil {
                pill.add(CMMotion.spring("position", from: NSValue(point: from), to: NSValue(point: pill.position)), forKey: "slide")
            }
        }
        if notify { onSelect?(index) }
    }
}

private final class CMSidebar: NSView {
    let nav: CMNavList

    init(items: [(String, String)], version: String) {
        nav = CMNavList(items: items)
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        let wordmark = NSTextField(labelWithAttributedString: NSAttributedString(string: "ClipMesh", attributes: [
            .font: CMFont.semibold(20), .foregroundColor: CMColor.text, .kern: -0.4,
        ]))
        wordmark.translatesAutoresizingMaskIntoConstraints = false
        let mark = CMBox(fill: CMColor.accent, radius: 4)
        let brand = cmHStack([mark, wordmark], spacing: 9)
        let footer = cmLabel(version.isEmpty ? "ClipMesh" : "ClipMesh \(version)", CMFont.regular(11), CMColor.textFaint)
        footer.toolTip = "Encrypted clipboard · Direct LAN transfer"
        let hairline = CMBox(fill: CMColor.line)
        for view in [brand, nav, footer, hairline] { addSubview(view) }
        NSLayoutConstraint.activate([
            mark.widthAnchor.constraint(equalToConstant: 8), mark.heightAnchor.constraint(equalToConstant: 8),
            brand.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 24), brand.topAnchor.constraint(equalTo: topAnchor, constant: 46),
            nav.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12), nav.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            nav.topAnchor.constraint(equalTo: brand.bottomAnchor, constant: 22),
            footer.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 24), footer.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -14),
            footer.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -18),
            hairline.trailingAnchor.constraint(equalTo: trailingAnchor), hairline.topAnchor.constraint(equalTo: topAnchor),
            hairline.bottomAnchor.constraint(equalTo: bottomAnchor), hairline.widthAnchor.constraint(equalToConstant: 1),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
}

// MARK: - Rows, tiles and panels

class CMDeviceRow: NSView {
    let avatar = CMAvatar()
    let titleLabel = cmLabel("", CMFont.medium(15))
    let captionLabel = cmLabel("", CMFont.regular(12), CMColor.textMuted)
    let trailing = cmHStack([], spacing: 6)
    private let separator = CMBox(fill: CMColor.line)
    var showsSeparator = false { didSet { separator.isHidden = !showsSeparator } }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        let text = cmVStack([titleLabel, captionLabel], spacing: 1)
        text.setClippingResistancePriority(.defaultLow, for: .horizontal)
        let row = cmHStack([avatar, text, cmSpacer(), trailing], spacing: 12)
        addSubview(row)
        addSubview(separator)
        separator.isHidden = true
        trailing.setContentCompressionResistancePriority(.required, for: .horizontal)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: leadingAnchor), row.trailingAnchor.constraint(equalTo: trailingAnchor),
            row.topAnchor.constraint(equalTo: topAnchor, constant: 9), row.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -9),
            heightAnchor.constraint(greaterThanOrEqualToConstant: 52),
            separator.topAnchor.constraint(equalTo: topAnchor), separator.heightAnchor.constraint(equalToConstant: 1),
            separator.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 46), separator.trailingAnchor.constraint(equalTo: trailingAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func configure(title: String, caption: String, symbol: String, online: Bool, captionColor: NSColor = CMColor.textMuted) {
        if titleLabel.stringValue != title { titleLabel.stringValue = title }
        if captionLabel.stringValue != caption { captionLabel.stringValue = caption }
        captionLabel.textColor = captionColor
        avatar.setSymbol(symbol)
        avatar.online = online
    }
}

final class CMTransferRow: CMDeviceRow {
    enum State: Equatable { case idle(enabled: Bool), sending(Double), sent }
    var onSend: (() -> Void)?
    var onFavorite: (() -> Void)?
    private let star = CMPillButton("", symbol: "star", style: .plain, height: 28)
    private let sendButton = CMPillButton("Send", style: .primary, height: 30)
    private let ring = CMProgressRing()
    private let line = CMProgressBar()
    private var state: State?
    private var favorite: Bool?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        star.handler = { [weak self] in self?.onFavorite?() }
        sendButton.handler = { [weak self] in self?.onSend?() }
        sendButton.widthAnchor.constraint(greaterThanOrEqualToConstant: 64).isActive = true
        for view in [star, ring, sendButton] { trailing.addArrangedSubview(view) }
        trailing.setCustomSpacing(10, after: star)
        ring.isHidden = true
        line.setThickness(3)
        line.isHidden = true
        addSubview(line)
        NSLayoutConstraint.activate([
            line.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 46), line.trailingAnchor.constraint(equalTo: trailingAnchor),
            line.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -2),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func apply(favorite isFavorite: Bool, state newState: State) {
        if favorite != isFavorite {
            favorite = isFavorite
            star.setSymbol(isFavorite ? "star.fill" : "star")
            star.tint = isFavorite ? CMColor.accent : CMColor.textFaint
            star.hoverTint = isFavorite ? CMColor.accent : CMColor.textSoft
            star.restingFill = isFavorite ? CMColor.accentSoft : nil
            star.toolTip = isFavorite ? "Trusted — can send to you without asking. Click to stop trusting." : "Trusted devices can send to you without asking"
            star.setAccessibilityLabel(isFavorite ? "Trusted" : "Trust this device")
        }
        let previous = state
        state = newState
        let animated = previous != nil && window != nil
        switch newState {
        case .idle(let enabled):
            swap(to: sendButton, animated: animated && previous != newState)
            sendButton.isEnabled = enabled
            ring.reset()
            line.isHidden = true
        case .sending(let value):
            swap(to: ring, animated: animated)
            ring.set(value, animated: animated)
            if line.isHidden { line.set(0, animated: false); line.isHidden = false }
            line.set(value, animated: animated)
        case .sent:
            swap(to: ring, animated: false)
            ring.showDone(animated: animated)
            line.set(1, animated: animated)
            CMMotion.after(0.5) { [weak self] in if self?.state == .sent { self?.line.isHidden = true } }
        }
    }

    private func swap(to view: NSView, animated: Bool) {
        let other: NSView = view === ring ? sendButton : ring
        guard view.isHidden || !other.isHidden else { return }
        other.isHidden = true
        view.isHidden = false
        if animated { CMMotion.enter(view, duration: 0.16) }
    }
}

private final class CMFileTile: CMHoverView {
    var onRemove: (() -> Void)?
    private let thumb = CMBox(fill: CMColor.fill06, radius: 12)
    private let imageLayer = CALayer()
    private let close = CMPillButton("", symbol: "xmark", style: .overlay, height: 20)

    init(url: URL?, moreCount: Int = 0) {
        super.init(frame: .zero)
        wantsLayer = true
        tracksHover = true
        translatesAutoresizingMaskIntoConstraints = false
        thumb.layer?.masksToBounds = true
        imageLayer.frame = CGRect(x: 0, y: 0, width: 76, height: 56)
        imageLayer.contentsGravity = .resizeAspectFill
        imageLayer.masksToBounds = true
        thumb.layer?.addSublayer(imageLayer)
        let name = cmLabel(url?.lastPathComponent ?? "more", CMFont.regular(11), url == nil ? CMColor.textMuted : CMColor.textSoft)
        name.alignment = .center
        name.lineBreakMode = .byTruncatingMiddle
        addSubview(thumb)
        addSubview(name)
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 76), heightAnchor.constraint(equalToConstant: 76),
            thumb.leadingAnchor.constraint(equalTo: leadingAnchor), thumb.trailingAnchor.constraint(equalTo: trailingAnchor),
            thumb.topAnchor.constraint(equalTo: topAnchor), thumb.heightAnchor.constraint(equalToConstant: 56),
            name.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 1), name.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -1),
            name.topAnchor.constraint(equalTo: thumb.bottomAnchor, constant: 5),
        ])
        if let url {
            let icon = NSImageView()
            icon.image = NSWorkspace.shared.icon(forFile: url.path)
            icon.imageScaling = .scaleProportionallyUpOrDown
            icon.translatesAutoresizingMaskIntoConstraints = false
            thumb.addSubview(icon)
            NSLayoutConstraint.activate([
                icon.centerXAnchor.constraint(equalTo: thumb.centerXAnchor), icon.centerYAnchor.constraint(equalTo: thumb.centerYAnchor),
                icon.widthAnchor.constraint(equalToConstant: 38), icon.heightAnchor.constraint(equalToConstant: 38),
            ])
            toolTip = url.path
            if CMThumbs.isImage(url) {
                CMThumbs.load(url, maxPixel: 220) { [weak self, weak icon] thumb in
                    guard let self, let thumb else { return }
                    CATransaction.begin()
                    CATransaction.setDisableActions(true)
                    self.imageLayer.contents = thumb.image
                    CATransaction.commit()
                    self.imageLayer.add(CMMotion.basic("opacity", from: 0, to: 1, duration: 0.2), forKey: "fade")
                    icon?.isHidden = true
                }
            }
            close.toolTip = "Remove"
            close.handler = { [weak self] in self?.onRemove?() }
            close.alphaValue = 0
            addSubview(close)
            NSLayoutConstraint.activate([
                close.topAnchor.constraint(equalTo: topAnchor, constant: 4), close.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -4),
            ])
        } else {
            let more = cmLabel("+\(moreCount)", CMFont.semibold(16), CMColor.textSoft)
            thumb.addSubview(more)
            NSLayoutConstraint.activate([more.centerXAnchor.constraint(equalTo: thumb.centerXAnchor), more.centerYAnchor.constraint(equalTo: thumb.centerYAnchor)])
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override func hoverChanged() {
        guard close.superview != nil else { return }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.16
            close.animator().alphaValue = isHovering ? 1 : 0
        }
    }
}

private final class CMDropZone: CMHoverView {
    var onClick: (() -> Void)?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        tracksHover = true
        translatesAutoresizingMaskIntoConstraints = false
        let icon = cmSymbol("arrow.down.doc", size: 22, weight: .regular, color: CMColor.textMuted)
        let title = cmLabel("Drop files or click to choose", CMFont.medium(14), CMColor.textSoft)
        let stack = cmVStack([icon, title], spacing: 10)
        stack.alignment = .centerX
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor), stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            heightAnchor.constraint(equalToConstant: 120),
        ])
        setAccessibilityElement(true)
        setAccessibilityRole(.button)
        setAccessibilityLabel("Choose files to send")
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 1, dy: 1), xRadius: 20, yRadius: 20)
        (isHovering ? CMColor.accentSoft : CMColor.fill05).setFill()
        path.fill()
        path.lineWidth = 1.5
        path.setLineDash([7, 6], count: 2, phase: 0)
        (isHovering ? CMColor.accent : CMColor.fill20).setStroke()
        path.stroke()
    }
    override func hoverChanged() { needsDisplay = true }
    override func hitTest(_ point: NSPoint) -> NSView? { super.hitTest(point) == nil ? nil : self }
    override func mouseDown(with event: NSEvent) { CMMotion.press(self, down: true) }
    override func mouseUp(with event: NSEvent) {
        CMMotion.press(self, down: false)
        if bounds.contains(convert(event.locationInWindow, from: nil)) { onClick?() }
    }
    override func accessibilityPerformPress() -> Bool { onClick?(); return true }
}

private final class CMBanner: CMBox {
    enum State { case progress, done, failed }
    private let icon = NSImageView()
    private let label = cmLabel("", CMFont.medium(13))
    private let percent = cmLabel("", CMFont.medium(12), CMColor.textSoft)
    private let bar = CMProgressBar()

    init() {
        super.init(fill: CMColor.accentSoft, radius: 12)
        icon.translatesAutoresizingMaskIntoConstraints = false
        percent.setContentCompressionResistancePriority(.required, for: .horizontal)
        let row = cmHStack([icon, label, cmSpacer(), percent], spacing: 8)
        addSubview(row)
        bar.setThickness(3)
        addSubview(bar)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12), row.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            row.topAnchor.constraint(equalTo: topAnchor, constant: 9), row.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -12),
            bar.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12), bar.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            bar.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -5),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func show(_ text: String, state: State, fraction: Double = 0) {
        label.stringValue = text
        let symbol: String, color: NSColor
        switch state {
        case .progress: symbol = "arrow.down.circle.fill"; color = CMColor.accent
        case .done: symbol = "checkmark.circle.fill"; color = CMColor.positive
        case .failed: symbol = "exclamationmark.circle.fill"; color = CMColor.negative
        }
        icon.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: 14, weight: .semibold))
        icon.contentTintColor = color
        CMMotion.animate(layer, to: color.withAlphaComponent(0.14).cgColor)
        percent.stringValue = state == .progress ? "\(Int((fraction * 100).rounded()))%" : ""
        bar.isHidden = state == .failed
        bar.color = state == .done ? CMColor.positive : CMColor.accent
        bar.set(state == .done ? 1 : fraction, animated: true)
    }
}

/// Image with rounded corners that keeps its aspect ratio inside the available width.
private final class CMImagePreview: NSView {
    private let imageView = NSImageView()
    private var aspect: NSLayoutConstraint?
    private var cap: NSLayoutConstraint?

    init(maxHeight: CGFloat, centered: Bool = false) {
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        imageView.translatesAutoresizingMaskIntoConstraints = false
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.wantsLayer = true
        imageView.layer?.cornerRadius = 14
        imageView.layer?.masksToBounds = true
        imageView.layer?.backgroundColor = CMColor.fill06.cgColor
        for orientation in [NSLayoutConstraint.Orientation.horizontal, .vertical] {
            imageView.setContentHuggingPriority(.init(100), for: orientation)
            imageView.setContentCompressionResistancePriority(.init(100), for: orientation)
        }
        addSubview(imageView)
        let preferred = imageView.heightAnchor.constraint(equalToConstant: maxHeight)
        preferred.priority = .init(200)
        NSLayoutConstraint.activate([
            imageView.topAnchor.constraint(equalTo: topAnchor), imageView.bottomAnchor.constraint(equalTo: bottomAnchor),
            centered ? imageView.centerXAnchor.constraint(equalTo: centerXAnchor) : imageView.leadingAnchor.constraint(equalTo: leadingAnchor),
            imageView.leadingAnchor.constraint(greaterThanOrEqualTo: leadingAnchor), imageView.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor),
            imageView.heightAnchor.constraint(lessThanOrEqualToConstant: maxHeight), preferred,
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func set(_ image: NSImage?, pixelSize: CGSize) {
        imageView.image = image
        aspect?.isActive = false
        cap?.isActive = false
        let ratio = pixelSize.height > 0 && pixelSize.width > 0 ? pixelSize.width / pixelSize.height : 1
        let scale = NSScreen.main?.backingScaleFactor ?? 2
        aspect = imageView.widthAnchor.constraint(equalTo: imageView.heightAnchor, multiplier: ratio)
        cap = imageView.heightAnchor.constraint(lessThanOrEqualToConstant: max(48, pixelSize.height / scale))
        aspect?.isActive = true
        cap?.isActive = true
    }
}

/// Watches a directory vnode (atomic temp-file + rename writes show up as directory
/// changes) and reports coalesced changes on the main queue. No polling.
private final class CMDirectoryWatcher {
    private let url: URL
    private let onChange: () -> Void
    private var source: DispatchSourceFileSystemObject?
    private var pending: DispatchWorkItem?

    init(url: URL, onChange: @escaping () -> Void) {
        self.url = url
        self.onChange = onChange
    }

    func start() {
        guard source == nil else { return }
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        let descriptor = Darwin.open(url.path, O_EVTONLY)
        guard descriptor >= 0 else { return }
        let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: descriptor, eventMask: [.write, .rename, .delete, .link], queue: .main)
        source.setEventHandler { [weak self] in
            guard let self, let current = self.source else { return }
            if !current.data.intersection([.rename, .delete]).isEmpty {
                // The directory itself moved/vanished: re-open on the new vnode.
                self.stop()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in self?.start() }
            }
            self.schedule()
        }
        source.setCancelHandler { Darwin.close(descriptor) }
        self.source = source
        source.resume()
    }

    func stop() {
        pending?.cancel()
        pending = nil
        source?.cancel()
        source = nil
    }

    private func schedule() {
        pending?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.onChange() }
        pending = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
    }
}

private struct CMRowItem {
    let key: String
    let title: String
    var caption = ""
    var symbol = "laptopcomputer"
    var online = false
    var placeholder = false
    var pulsing = false
    var captionColor = CMColor.textMuted
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private enum SyncHealth { case starting, on, recovering, stopped }

    private var window: NSWindow!
    private var rootView: CMRootView!
    private var sidebar: CMSidebar!
    private var contentHost: NSView!
    private var pages: [NSView] = []
    private var selectedTab = 0
    private var statusPill: CMStatusPill!
    private var clipboardThumb: CMBox!
    private var clipboardThumbLayer = CALayer()
    private var clipboardGlyph: NSImageView!
    private var clipboardGlyphText: NSTextField!
    private var clipboardTitle: NSTextField!
    private var clipboardCaption: NSTextField!
    private var clipboardSnippet: NSTextField!
    private var deviceLines: [NSTextField] = []
    private var clipboardChangeCount = -1
    private var clipboardContent: CMClipboardContent = .empty
    private var clipboardLoadToken = 0
    private var peersStack: NSStackView!
    private var nearbyPairStack: NSStackView!
    private var devicesRefreshButton: CMPillButton!
    private var transferRefreshButton: CMPillButton!
    private var incomingBanner: CMBanner!
    private var incomingHideToken = 0
    private var dropZone: CMDropZone!
    private var filesPanel: NSStackView!
    private var filesSummaryLabel: NSTextField!
    private var transferFilesStack: NSStackView!
    private var transferDeviceStack: NSStackView!
    private var transferFiles: [URL] = []
    private var sendingFingerprint: String?
    private var sendProgressValue: Double = 0
    private var sendCaption = ""
    private var sentFingerprint: String?
    private var deviceNameValue: NSTextField!
    private var deviceIDValue: NSTextField!
    private var sendToggle: CMToggle!
    private var receiveToggle: CMToggle!
    private var receiveFolderValue: NSTextField!
    private var shareStatusValue: NSTextField!
    private var nearbyCodePanel: NSPanel?
    private var supportWatcher: CMDirectoryWatcher?
    private var diskStamp = ""
    private var peerStatusWork: DispatchWorkItem?
    private var nearbyHeader: NSTextField!
    private var pendingSharedFiles: [URL] = []
    private var daemon: Process?
    private var logHandle: FileHandle?
    private var statusItem: NSStatusItem?
    private var statusMenu: NSMenu?
    private var quitting = false
    private var latestState: UIState?
    private var daemonRestartAttempts = 0
    private var daemonRestartWorkItem: DispatchWorkItem?
    private var instanceLockFD: Int32 = -1

    private var appVersion: String { (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "" }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        CMFont.registerBundledFonts()
        do {
            guard let descriptor = try Runtime.acquireInstanceLock() else {
                if let identifier = Bundle.main.bundleIdentifier {
                    NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
                        .first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier })?
                        .activate(options: [.activateAllWindows])
                }
                NSApp.terminate(nil)
                return
            }
            instanceLockFD = descriptor
        } catch {
            buildWindow()
            showError(error.localizedDescription)
            return
        }
        buildMainMenu()
        buildWindow()
        buildStatusItem()
        NSApp.servicesProvider = self
        NSUpdateDynamicServices()
        registerShareExtension()
        LocalTransferManager.shared.incomingPrompt = { sender, files in
            TransferDialogs.ask(sender: sender, files: files)
        }
        LocalTransferManager.shared.incomingProgress = { [weak self] sender, file, fraction, complete in
            self?.showIncomingTransferProgress(sender: sender, file: file, fraction: fraction, complete: complete)
        }
        LocalTransferManager.shared.devicesChanged = { [weak self] in self?.nearbyDevicesChanged() }
        LocalTransferManager.shared.start(aliasProvider: { [weak self] in
            self?.latestState?.deviceName ?? Runtime.deviceName()
        })
        let nearbyPair = NearbyPairingManager.shared
        nearbyPair.aliasProvider = { [weak self] in self?.latestState?.deviceName ?? Runtime.deviceName() }
        nearbyPair.fingerprintProvider = { LocalTransferManager.shared.fingerprint }
        nearbyPair.deviceIDProvider = { [weak self] in self?.latestState?.deviceID ?? ((try? Runtime.uiState().deviceID) ?? "") }
        nearbyPair.peerConsumer = { [weak self] id, name in
            guard let self else { return false }
            var ok = false
            let work = {
                self.stopDaemon()
                do { try Runtime.seedPeer(id, name: name); try self.startDaemon(); self.refreshHome(); ok = true }
                catch { try? self.startDaemon(); self.showError(error.localizedDescription) }
            }
            if Thread.isMainThread { work() } else { DispatchQueue.main.sync(execute: work) }
            return ok
        }
        nearbyPair.approvalPrompt = { [weak self] sender in self?.approveNearbyPair(sender) ?? false }
        nearbyPair.codePrompt = { [weak self] sender, submit in self?.promptNearbyCode(sender, submit: submit) }
        nearbyPair.credentialConsumer = { [weak self] uri, sender in self?.acceptNearbyCredential(uri, sender: sender) ?? false }
        nearbyPair.start()
        showWindow()

        do {
            try Runtime.prepareFirstRun()
            try startDaemon()
            refreshHome()
        } catch {
            setSync(.stopped, detail: error.localizedDescription)
            showError(error.localizedDescription)
        }
        if !pendingSharedFiles.isEmpty {
            let files = pendingSharedFiles
            pendingSharedFiles = []
            receiveSharedFiles(files)
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        let files = urls.filter { $0.scheme == "clipmesh-share" }.flatMap { CMShareIntake.files(from: $0) }
        if !files.isEmpty { receiveSharedFiles(files) }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        guard window?.isVisible == true else { return }
        if selectedTab == 0 { refreshClipboardPreview() }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        supportWatcher?.stop()
        NearbyPairingManager.shared.stop()
        LocalTransferManager.shared.stop()
        stopDaemon()
        logHandle?.closeFile()
        Runtime.releaseInstanceLock(instanceLockFD)
        instanceLockFD = -1
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hideWindow()
        return false
    }

    func windowDidBecomeKey(_ notification: Notification) {
        if selectedTab == 0 { refreshClipboardPreview() }
    }

    // MARK: Menus

    private func buildMainMenu() {
        let main = NSMenu()

        let appRoot = NSMenuItem()
        let appMenu = NSMenu(title: "ClipMesh")
        appMenu.addItem(withTitle: "About ClipMesh", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let settings = NSMenuItem(title: "Settings…", action: #selector(showSettingsTab), keyEquivalent: ",")
        settings.target = self
        appMenu.addItem(settings)
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide ClipMesh", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = NSMenuItem(title: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        appMenu.addItem(quit)
        main.addItem(appRoot)
        main.setSubmenu(appMenu, for: appRoot)

        let fileRoot = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        let sendItem = NSMenuItem(title: "Send Files…", action: #selector(sendFiles), keyEquivalent: "o")
        sendItem.target = self
        fileMenu.addItem(sendItem)
        fileMenu.addItem(.separator())
        fileMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        main.addItem(fileRoot)
        main.setSubmenu(fileMenu, for: fileRoot)

        let editRoot = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redo)
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(editRoot)
        main.setSubmenu(editMenu, for: editRoot)

        let viewRoot = NSMenuItem()
        let viewMenu = NSMenu(title: "View")
        for (title, key, selector) in [("Clipboard", "1", #selector(showClipboardTab)), ("Transfer", "2", #selector(showTransferTab)), ("Settings", "3", #selector(showSettingsTab))] {
            let item = NSMenuItem(title: title, action: selector, keyEquivalent: key)
            item.target = self
            viewMenu.addItem(item)
        }
        main.addItem(viewRoot)
        main.setSubmenu(viewMenu, for: viewRoot)

        let windowRoot = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        main.addItem(windowRoot)
        main.setSubmenu(windowMenu, for: windowRoot)
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = main
    }

    // MARK: Window and pages

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 980, height: 680),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "ClipMesh"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = CMColor.background
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 820, height: 580)
        window.center(); window.delegate = self
        CMDialog.hostWindow = window

        rootView = CMRootView(frame: NSRect(x: 0, y: 0, width: 980, height: 680))
        rootView.onFiles = { [weak self] urls in self?.receiveSharedFiles(urls) }
        window.contentView = rootView

        sidebar = CMSidebar(items: [("Clipboard", "doc.on.clipboard"), ("Transfer", "arrow.left.arrow.right"), ("Settings", "gearshape")], version: appVersion)
        sidebar.nav.onSelect = { [weak self] index in self?.selectTab(index, animated: true) }
        contentHost = NSView()
        contentHost.wantsLayer = true
        contentHost.translatesAutoresizingMaskIntoConstraints = false
        rootView.addSubview(sidebar)
        rootView.addSubview(contentHost)
        NSLayoutConstraint.activate([
            sidebar.leadingAnchor.constraint(equalTo: rootView.leadingAnchor), sidebar.topAnchor.constraint(equalTo: rootView.topAnchor),
            sidebar.bottomAnchor.constraint(equalTo: rootView.bottomAnchor), sidebar.widthAnchor.constraint(equalToConstant: 200),
            contentHost.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor), contentHost.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            contentHost.topAnchor.constraint(equalTo: rootView.topAnchor), contentHost.bottomAnchor.constraint(equalTo: rootView.bottomAnchor),
        ])

        pages = [buildClipboardPage(), buildTransferPage(), buildSettingsPage()]
        for page in pages {
            page.translatesAutoresizingMaskIntoConstraints = false
            page.wantsLayer = true
            contentHost.addSubview(page)
            NSLayoutConstraint.activate([
                page.leadingAnchor.constraint(equalTo: contentHost.leadingAnchor), page.trailingAnchor.constraint(equalTo: contentHost.trailingAnchor),
                page.topAnchor.constraint(equalTo: contentHost.topAnchor), page.bottomAnchor.constraint(equalTo: contentHost.bottomAnchor),
            ])
        }
        updateTransferSelection(animated: false)
        selectTab(0, animated: false)
    }

    private func makePage(title: String, trailing: NSView?, showsDevice: Bool = false) -> (NSScrollView, NSStackView) {
        let document = CMFlippedView()
        document.translatesAutoresizingMaskIntoConstraints = false
        let stack = cmVStack([], spacing: 12)
        stack.edgeInsets = NSEdgeInsets(top: 38, left: 24, bottom: 28, right: 24)
        document.addSubview(stack)
        let scroll = CMScrollView()
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.documentView = document
        let fill = stack.widthAnchor.constraint(equalTo: document.widthAnchor)
        fill.priority = .init(999)
        NSLayoutConstraint.activate([
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            stack.topAnchor.constraint(equalTo: document.topAnchor), stack.bottomAnchor.constraint(equalTo: document.bottomAnchor),
            stack.centerXAnchor.constraint(equalTo: document.centerXAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualToConstant: 860), fill,
        ])
        let titleLabel = NSTextField(labelWithAttributedString: NSAttributedString(string: title, attributes: [
            .font: CMFont.semibold(24), .foregroundColor: CMColor.text, .kern: -0.3,
        ]))
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        var titleViews: [NSView] = [titleLabel]
        if showsDevice {
            let line = cmLabel("This device · \(latestState?.deviceName ?? Runtime.deviceName())", CMFont.regular(12), CMColor.textMuted)
            deviceLines.append(line)
            titleViews.append(line)
        }
        let titles = cmVStack(titleViews, spacing: 2)
        let header = cmHStack([titles, cmSpacer()] + (trailing.map { [$0] } ?? []), spacing: 12)
        addFull(header, to: stack)
        stack.setCustomSpacing(16, after: header)
        return (scroll, stack)
    }

    private func addFull(_ view: NSView, to stack: NSStackView) {
        stack.addArrangedSubview(view)
        view.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -(stack.edgeInsets.left + stack.edgeInsets.right)).isActive = true
    }

    private func settingRow(_ title: String, caption: NSTextField? = nil, trailing: NSView? = nil, titleColor: NSColor = CMColor.text) -> NSView {
        let titleLabel = cmLabel(title, CMFont.medium(14), titleColor)
        let text = cmVStack([titleLabel] + (caption.map { [$0] } ?? []), spacing: 2)
        text.setClippingResistancePriority(.defaultLow, for: .horizontal)
        let row = cmHStack([text, cmSpacer()] + (trailing.map { [$0] } ?? []), spacing: 12)
        row.edgeInsets = NSEdgeInsets(top: 6, left: 0, bottom: 6, right: 0)
        row.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
        return row
    }

    private func hairline() -> NSView {
        let line = CMBox(fill: CMColor.line)
        line.heightAnchor.constraint(equalToConstant: 1).isActive = true
        return line
    }

    private func buildClipboardPage() -> NSView {
        statusPill = CMStatusPill()
        statusPill.set("Starting…", color: CMColor.textMuted)
        let (scroll, stack) = makePage(title: "Clipboard", trailing: statusPill, showsDevice: true)

        // Current clipboard: one compact, clickable row.
        let current = CMCard(padding: 14)
        clipboardThumb = CMBox(fill: CMColor.fill07, radius: 12)
        clipboardThumb.layer?.masksToBounds = true
        clipboardThumbLayer.frame = CGRect(x: 0, y: 0, width: 64, height: 64)
        clipboardThumbLayer.contentsGravity = .resizeAspectFill
        clipboardThumbLayer.masksToBounds = true
        clipboardThumb.layer?.addSublayer(clipboardThumbLayer)
        clipboardGlyph = NSImageView()
        clipboardGlyph.translatesAutoresizingMaskIntoConstraints = false
        clipboardGlyph.imageScaling = .scaleProportionallyUpOrDown
        clipboardGlyph.contentTintColor = CMColor.textMuted
        clipboardGlyphText = cmLabel("T", CMFont.semibold(26), CMColor.textSoft)
        clipboardThumb.addSubview(clipboardGlyph)
        clipboardThumb.addSubview(clipboardGlyphText)
        clipboardTitle = cmLabel("", CMFont.medium(14))
        clipboardTitle.lineBreakMode = .byTruncatingMiddle
        clipboardCaption = cmLabel("", CMFont.regular(12), CMColor.textMuted)
        clipboardSnippet = cmLabel("", CMFont.regular(13), CMColor.textSoft, wrap: true)
        clipboardSnippet.maximumNumberOfLines = 2
        clipboardSnippet.preferredMaxLayoutWidth = 560
        clipboardSnippet.lineBreakMode = .byTruncatingTail
        clipboardSnippet.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let text = cmVStack([clipboardTitle, clipboardCaption, clipboardSnippet], spacing: 2)
        text.setClippingResistancePriority(.defaultLow, for: .horizontal)
        let chevron = cmSymbol("chevron.right", size: 12, weight: .semibold, color: CMColor.textFaint)
        let row = cmHStack([clipboardThumb, text, cmSpacer(), chevron], spacing: 14)
        NSLayoutConstraint.activate([
            clipboardThumb.widthAnchor.constraint(equalToConstant: 64), clipboardThumb.heightAnchor.constraint(equalToConstant: 64),
            clipboardGlyph.centerXAnchor.constraint(equalTo: clipboardThumb.centerXAnchor), clipboardGlyph.centerYAnchor.constraint(equalTo: clipboardThumb.centerYAnchor),
            clipboardGlyph.widthAnchor.constraint(equalToConstant: 34), clipboardGlyph.heightAnchor.constraint(equalToConstant: 34),
            clipboardGlyphText.centerXAnchor.constraint(equalTo: clipboardThumb.centerXAnchor), clipboardGlyphText.centerYAnchor.constraint(equalTo: clipboardThumb.centerYAnchor),
            clipboardSnippet.widthAnchor.constraint(lessThanOrEqualTo: text.widthAnchor),
        ])
        current.add(row)
        current.onClick = { [weak self] in self?.viewClipboard() }
        current.toolTip = "Current clipboard — click to view"
        current.setAccessibilityRole(.button)
        current.setAccessibilityLabel("Current clipboard")
        addFull(current, to: stack)

        let devices = CMCard(padding: 14, spacing: 4)
        devicesRefreshButton = CMPillButton("", symbol: "arrow.clockwise", style: .plain, height: 28)
        devicesRefreshButton.toolTip = "Refresh"
        devicesRefreshButton.handler = { [weak self] in self?.refreshDevicesPressed() }
        let add = CMPillButton("", symbol: "plus", style: .plain, height: 28) { [weak self] in self?.pairWithCode() }
        add.toolTip = "Pair with a code"
        devices.add(cmHStack([cmSection("Devices"), cmSpacer(), devicesRefreshButton, add], spacing: 2))
        peersStack = cmListStack()
        peersStack.spacing = 0
        devices.add(peersStack)
        // The Nearby caption is the first arranged row of nearbyPairStack; the whole
        // section is hidden when no unpaired device is around (no filler text).
        nearbyPairStack = cmListStack()
        nearbyPairStack.spacing = 0
        nearbyHeader = cmLabel("Nearby", CMFont.medium(12), CMColor.textMuted)
        nearbyHeader.identifier = NSUserInterfaceItemIdentifier("__header")
        nearbyPairStack.addArrangedSubview(nearbyHeader)
        nearbyPairStack.setCustomSpacing(2, after: nearbyHeader)
        nearbyPairStack.edgeInsets = NSEdgeInsets(top: 12, left: 0, bottom: 0, right: 0)
        devices.add(nearbyPairStack)
        nearbyPairStack.isHidden = true
        addFull(devices, to: stack)
        return scroll
    }

    private func buildTransferPage() -> NSView {
        let choose = CMPillButton("Choose files", symbol: "plus", style: .secondary, height: 32) { [weak self] in self?.chooseTransferFiles() }
        let (scroll, stack) = makePage(title: "Transfer", trailing: choose, showsDevice: true)

        incomingBanner = CMBanner()
        addFull(incomingBanner, to: stack)
        incomingBanner.isHidden = true

        let selection = CMCard(padding: 14)
        dropZone = CMDropZone()
        dropZone.onClick = { [weak self] in self?.chooseTransferFiles() }
        selection.add(dropZone)
        filesSummaryLabel = cmLabel("", CMFont.medium(14))
        let clear = CMPillButton("Clear", style: .text, height: 28) { [weak self] in self?.clearTransferSelection(animated: true) }
        let header = cmHStack([filesSummaryLabel, cmSpacer(), clear], spacing: 8)
        header.heightAnchor.constraint(equalToConstant: 28).isActive = true
        transferFilesStack = NSStackView()
        transferFilesStack.orientation = .horizontal
        transferFilesStack.alignment = .top
        transferFilesStack.spacing = 10
        transferFilesStack.translatesAutoresizingMaskIntoConstraints = false
        let tilesDocument = CMFlippedView()
        tilesDocument.translatesAutoresizingMaskIntoConstraints = false
        tilesDocument.addSubview(transferFilesStack)
        let tilesScroll = CMScrollView()
        tilesScroll.hasHorizontalScroller = true
        tilesScroll.hasVerticalScroller = false
        tilesScroll.documentView = tilesDocument
        NSLayoutConstraint.activate([
            transferFilesStack.leadingAnchor.constraint(equalTo: tilesDocument.leadingAnchor), transferFilesStack.trailingAnchor.constraint(equalTo: tilesDocument.trailingAnchor),
            transferFilesStack.topAnchor.constraint(equalTo: tilesDocument.topAnchor), transferFilesStack.bottomAnchor.constraint(equalTo: tilesDocument.bottomAnchor),
            tilesDocument.heightAnchor.constraint(equalToConstant: 80), tilesScroll.heightAnchor.constraint(equalToConstant: 80),
        ])
        filesPanel = cmVStack([header, tilesScroll], spacing: 8)
        header.widthAnchor.constraint(equalTo: filesPanel.widthAnchor).isActive = true
        tilesScroll.widthAnchor.constraint(equalTo: filesPanel.widthAnchor).isActive = true
        selection.add(filesPanel)
        filesPanel.isHidden = true
        addFull(selection, to: stack)

        let sendCard = CMCard(padding: 14, spacing: 4)
        transferRefreshButton = CMPillButton("", symbol: "arrow.clockwise", style: .plain, height: 28)
        transferRefreshButton.toolTip = "Look again"
        transferRefreshButton.handler = { [weak self] in
            guard let self else { return }
            CMMotion.spin(self.transferRefreshButton)
            LocalTransferManager.shared.discoverNow()
            self.refreshTransferDevices()
        }
        sendCard.add(cmHStack([cmSection("Send to"), cmSpacer(), transferRefreshButton], spacing: 2))
        transferDeviceStack = cmListStack()
        transferDeviceStack.spacing = 0
        sendCard.add(transferDeviceStack)
        addFull(sendCard, to: stack)
        return scroll
    }

    private func buildSettingsPage() -> NSView {
        let (scroll, stack) = makePage(title: "Settings", trailing: nil)

        let device = CMCard(padding: 14, spacing: 0)
        device.add(cmSection("This device"), spacingAfter: 2)
        deviceNameValue = cmLabel(Runtime.deviceName(), CMFont.regular(12), CMColor.textMuted)
        device.add(settingRow("Device name", caption: deviceNameValue, trailing: CMPillButton("Rename", style: .secondary, height: 28) { [weak self] in self?.renameDevice() }))
        device.add(hairline())
        deviceIDValue = cmLabel("", .monospacedSystemFont(ofSize: 11, weight: .regular), CMColor.textMuted)
        deviceIDValue.isSelectable = true
        deviceIDValue.lineBreakMode = .byTruncatingMiddle
        device.add(settingRow("Device ID", caption: deviceIDValue))
        addFull(device, to: stack)

        let clipboard = CMCard(padding: 14, spacing: 0)
        clipboard.add(cmSection("Clipboard"), spacingAfter: 2)
        sendToggle = CMToggle()
        sendToggle.onChange = { [weak self] _ in self?.syncSwitchChanged() }
        receiveToggle = CMToggle()
        receiveToggle.onChange = { [weak self] _ in self?.syncSwitchChanged() }
        clipboard.add(settingRow("Send clipboard", trailing: sendToggle))
        clipboard.add(hairline())
        clipboard.add(settingRow("Receive clipboard", trailing: receiveToggle))
        addFull(clipboard, to: stack)

        let files = CMCard(padding: 14, spacing: 0)
        files.add(cmSection("File transfer"), spacingAfter: 2)
        receiveFolderValue = cmLabel(LocalTransferManager.shared.outputFolderURL.path, CMFont.regular(12), CMColor.textMuted)
        receiveFolderValue.lineBreakMode = .byTruncatingMiddle
        files.add(settingRow("Receive folder", caption: receiveFolderValue, trailing: CMPillButton("Change", style: .secondary, height: 28) { [weak self] in
            self?.chooseOutputFolder()
        }), spacingAfter: 6)
        let favorites = cmLabel("Trusted (starred) devices save files automatically. Others ask first.", CMFont.regular(12), CMColor.textMuted, wrap: true)
        files.add(favorites)
        addFull(files, to: stack)

        let pairing = CMCard(padding: 14, spacing: 0)
        pairing.add(cmSection("Pairing"), spacingAfter: 2)
        pairing.add(settingRow("Pair with a code", trailing: CMPillButton("Pair", style: .secondary, height: 28) { [weak self] in self?.pairWithCode() }))
        pairing.add(hairline())
        pairing.add(settingRow("Copy my pairing code", trailing: CMPillButton("Copy", style: .secondary, height: 28) { [weak self] in self?.copyPairingLink() }))
        pairing.add(hairline())
        pairing.add(settingRow("Create new private space", trailing: CMPillButton("Create", style: .secondary, height: 28) { [weak self] in self?.createNewSpace() }))
        pairing.add(hairline())
        pairing.add(settingRow("Reset all pairing", trailing: CMPillButton("Reset", style: .destructive, height: 28) { [weak self] in self?.resetPairing() }, titleColor: CMColor.negative))
        addFull(pairing, to: stack)

        let finder = CMCard(padding: 14, spacing: 0)
        finder.add(cmSection("macOS"), spacingAfter: 2)
        shareStatusValue = cmLabel("Checking…", CMFont.regular(12), CMColor.textMuted)
        finder.add(settingRow("Finder Share extension", caption: shareStatusValue, trailing: CMPillButton("Refresh", style: .secondary, height: 28) { [weak self] in
            self?.registerShareExtension(showResult: true)
        }))
        addFull(finder, to: stack)

        let footer = cmVStack([
            cmLabel("ClipMesh \(appVersion)", CMFont.medium(12), CMColor.textFaint),
            cmLabel("Clipboard sync is end-to-end encrypted. Files go directly between your devices.", CMFont.regular(12), CMColor.textFaint, wrap: true),
        ], spacing: 4)
        footer.edgeInsets = NSEdgeInsets(top: 6, left: 4, bottom: 0, right: 4)
        addFull(footer, to: stack)
        return scroll
    }

    @objc private func showClipboardTab() { showWindow(); selectTab(0) }
    @objc private func showTransferTab() { showWindow(); selectTab(1) }
    @objc private func showSettingsTab() { showWindow(); selectTab(2) }

    private func selectTab(_ index: Int, animated: Bool = true) {
        guard pages.indices.contains(index) else { return }
        let previous = selectedTab
        selectedTab = index
        let animate = animated && previous != index && window?.isVisible == true
        sidebar?.nav.select(index, animated: animate)
        for (i, page) in pages.enumerated() {
            guard let layer = page.layer else { page.isHidden = i != index; continue }
            if i == index {
                layer.removeAnimation(forKey: "pageOut")
                page.isHidden = false
                page.alphaValue = 1
                if animate { CMMotion.enter(page, dy: index > previous ? -10 : 10, duration: 0.22) }
            } else if animate && i == previous && !page.isHidden {
                let fade = CMMotion.basic("opacity", from: 1, to: 0, duration: 0.12)
                fade.fillMode = .forwards
                fade.isRemovedOnCompletion = false
                CATransaction.begin()
                CATransaction.setCompletionBlock { [weak self, weak page] in
                    guard let self, let page, self.selectedTab != i else { return }
                    page.isHidden = true
                    page.layer?.removeAnimation(forKey: "pageOut")
                }
                layer.add(fade, forKey: "pageOut")
                CATransaction.commit()
            } else {
                layer.removeAnimation(forKey: "pageOut")
                page.isHidden = true
            }
        }
        switch index {
        case 0:
            LocalTransferManager.shared.discoverNow(); refreshNearbyPairDevices(); refreshClipboardPreview()
        case 1:
            LocalTransferManager.shared.discoverNow(); refreshTransferDevices()
        default:
            syncSettingsControls(); refreshShareExtensionStatus()
        }
    }

    // MARK: Clipboard preview (event-driven: tab select, window key, app activation)

    private func refreshClipboardPreview(force: Bool = false) {
        guard clipboardTitle != nil else { return }
        let pasteboard = NSPasteboard.general
        guard force || pasteboard.changeCount != clipboardChangeCount else { return }
        let firstRender = clipboardChangeCount == -1
        clipboardChangeCount = pasteboard.changeCount
        clipboardContent = CMClipboardReader.read(pasteboard)
        clipboardLoadToken += 1
        let token = clipboardLoadToken
        var glyph: NSImage?
        var letter = false
        var thumb: CGImage?
        var title = "", caption = "", snippet = ""
        switch clipboardContent {
        case .empty:
            title = "Clipboard is empty"
            glyph = NSImage(systemSymbolName: "doc.on.clipboard", accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: 22, weight: .regular))
        case .unsupported:
            title = "Clipboard content"
            caption = "Can’t be previewed"
            glyph = NSImage(systemSymbolName: "questionmark.square.dashed", accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: 22, weight: .regular))
        case .text(let text):
            letter = true
            title = "Text"
            caption = "\(text.count) character\(text.count == 1 ? "" : "s")"
            snippet = text.split(whereSeparator: \.isNewline).prefix(2).joined(separator: "\n").trimmingCharacters(in: .whitespaces)
            snippet = String(snippet.prefix(300))
        case .image(let image, let format, let size):
            title = "Image"
            caption = "\(format) · \(Int(size.width))×\(Int(size.height))"
            thumb = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
        case .imageFile(let url):
            title = url.lastPathComponent
            caption = CMThumbs.format(of: url)
            glyph = NSWorkspace.shared.icon(forFile: url.path)
            CMThumbs.load(url, maxPixel: 192) { [weak self] loaded in
                guard let self, self.clipboardLoadToken == token, let loaded else { return }
                self.clipboardCaption.stringValue = "\(loaded.format) · \(Int(loaded.pixelSize.width))×\(Int(loaded.pixelSize.height))"
                self.setClipboardThumb(loaded.image, animated: true)
                self.clipboardGlyph.isHidden = true
            }
        case .files(let urls):
            title = "\(urls.count) file\(urls.count == 1 ? "" : "s")"
            caption = urls.prefix(3).map(\.lastPathComponent).joined(separator: ", ") + (urls.count > 3 ? " +\(urls.count - 3)" : "")
            if let first = urls.first {
                glyph = NSWorkspace.shared.icon(forFile: first.path)
                if CMThumbs.isImage(first) {
                    CMThumbs.load(first, maxPixel: 192) { [weak self] loaded in
                        guard let self, self.clipboardLoadToken == token, let loaded else { return }
                        self.setClipboardThumb(loaded.image, animated: true)
                        self.clipboardGlyph.isHidden = true
                    }
                }
            }
        }
        clipboardTitle.stringValue = title
        clipboardTitle.textColor = { if case .empty = clipboardContent { return CMColor.textMuted } else { return CMColor.text } }()
        clipboardCaption.stringValue = caption
        clipboardCaption.isHidden = caption.isEmpty
        clipboardSnippet.stringValue = snippet
        clipboardSnippet.isHidden = snippet.isEmpty
        clipboardGlyph.image = glyph
        clipboardGlyph.isHidden = glyph == nil
        clipboardGlyphText.isHidden = !letter
        setClipboardThumb(thumb, animated: false)
        if !firstRender && window?.isVisible == true, let layer = clipboardThumb.superview?.layer {
            layer.add(CMMotion.basic("opacity", from: 0.35, to: 1, duration: 0.2), forKey: "refresh")
        }
    }

    private func setClipboardThumb(_ image: CGImage?, animated: Bool) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        clipboardThumbLayer.contents = image
        CATransaction.commit()
        if animated && image != nil { clipboardThumbLayer.add(CMMotion.basic("opacity", from: 0, to: 1, duration: 0.18), forKey: "fade") }
    }

    @objc private func viewClipboard() {
        refreshClipboardPreview()
        let inner: CGFloat = 592
        let accessory: NSView
        switch clipboardContent {
        case .empty:
            CMDialog.present(title: "Current clipboard", message: "Clipboard is empty.", width: 440)
            return
        case .unsupported:
            CMDialog.present(title: "Current clipboard", message: "This content can’t be previewed.", width: 440)
            return
        case .text(let text):
            accessory = textViewer(String(text.prefix(200_000)), width: inner)
        case .image(let image, let format, let size):
            let preview = CMImagePreview(maxHeight: 440, centered: true)
            preview.set(image, pixelSize: size)
            accessory = captioned(preview, "\(format) · \(Int(size.width))×\(Int(size.height))")
        case .imageFile(let url):
            let preview = CMImagePreview(maxHeight: 440, centered: true)
            if let thumb = CMThumbs.loadSync(url, maxPixel: 1800) {
                preview.set(thumb.nsImage, pixelSize: thumb.pixelSize)
                accessory = captioned(preview, "\(url.lastPathComponent) · \(thumb.format) · \(Int(thumb.pixelSize.width))×\(Int(thumb.pixelSize.height))")
            } else {
                preview.set(NSWorkspace.shared.icon(forFile: url.path), pixelSize: CGSize(width: 256, height: 256))
                accessory = captioned(preview, url.lastPathComponent)
            }
        case .files(let urls):
            accessory = fileList(urls, width: inner)
        }
        CMDialog.present(title: "Current clipboard", message: "", accessory: accessory, buttons: ["Done"], width: inner + 48)
    }

    private func captioned(_ view: NSView, _ caption: String) -> NSView {
        let label = cmLabel(caption, CMFont.regular(12), CMColor.textMuted)
        label.lineBreakMode = .byTruncatingMiddle
        let box = cmVStack([view, label], spacing: 10)
        box.alignment = .centerX
        view.widthAnchor.constraint(equalTo: box.widthAnchor).isActive = true
        label.widthAnchor.constraint(lessThanOrEqualTo: box.widthAnchor).isActive = true
        return box
    }

    private func textViewer(_ text: String, width: CGFloat) -> NSView {
        let textView = NSTextView(frame: NSRect(x: 0, y: 0, width: width, height: 100))
        textView.isEditable = false
        textView.isSelectable = true
        textView.drawsBackground = false
        textView.textColor = CMColor.textSoft
        textView.font = CMFont.regular(13)
        textView.textContainerInset = NSSize(width: 10, height: 12)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.string = text
        var height: CGFloat = 360
        if let manager = textView.layoutManager, let container = textView.textContainer {
            manager.ensureLayout(for: container)
            height = min(360, max(64, ceil(manager.usedRect(for: container).height) + 26))
        }
        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.contentView.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay
        scroll.documentView = textView
        let box = CMBox(fill: CMColor.fill05, radius: 14, border: CMColor.line)
        box.layer?.masksToBounds = true
        scroll.translatesAutoresizingMaskIntoConstraints = false
        box.addSubview(scroll)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: box.leadingAnchor), scroll.trailingAnchor.constraint(equalTo: box.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: box.topAnchor), scroll.bottomAnchor.constraint(equalTo: box.bottomAnchor),
            box.heightAnchor.constraint(equalToConstant: height),
        ])
        return box
    }

    private func fileList(_ urls: [URL], width: CGFloat) -> NSView {
        let list = cmVStack([], spacing: 6)
        list.edgeInsets = NSEdgeInsets(top: 4, left: 0, bottom: 4, right: 0)
        for url in urls.prefix(200) {
            let thumb = CMBox(fill: CMColor.fill06, radius: 8)
            thumb.layer?.masksToBounds = true
            let icon = NSImageView()
            icon.imageScaling = .scaleProportionallyUpOrDown
            icon.translatesAutoresizingMaskIntoConstraints = false
            if CMThumbs.isImage(url), let image = CMThumbs.loadSync(url, maxPixel: 96) {
                icon.image = image.nsImage
                icon.imageScaling = .scaleAxesIndependently
            } else {
                icon.image = NSWorkspace.shared.icon(forFile: url.path)
            }
            thumb.addSubview(icon)
            NSLayoutConstraint.activate([
                thumb.widthAnchor.constraint(equalToConstant: 36), thumb.heightAnchor.constraint(equalToConstant: 36),
                icon.centerXAnchor.constraint(equalTo: thumb.centerXAnchor), icon.centerYAnchor.constraint(equalTo: thumb.centerYAnchor),
                icon.widthAnchor.constraint(equalToConstant: 36), icon.heightAnchor.constraint(equalToConstant: 36),
            ])
            let name = cmLabel(url.lastPathComponent, CMFont.medium(13), CMColor.text)
            name.lineBreakMode = .byTruncatingMiddle
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize.map { cmByteString(Int64($0)) } ?? ""
            let detail = cmLabel(size.isEmpty ? url.deletingLastPathComponent().path : size, CMFont.regular(11), CMColor.textMuted)
            detail.lineBreakMode = .byTruncatingMiddle
            let row = cmHStack([thumb, cmVStack([name, detail], spacing: 2)], spacing: 12)
            list.addArrangedSubview(row)
            row.widthAnchor.constraint(equalTo: list.widthAnchor).isActive = true
        }
        if urls.count > 200 { list.addArrangedSubview(cmLabel("+\(urls.count - 200) more", CMFont.regular(12), CMColor.textMuted)) }
        let rows = CGFloat(min(urls.count, 200))
        let height = min(360, rows * 42 + 8)
        let document = CMFlippedView()
        document.translatesAutoresizingMaskIntoConstraints = false
        document.addSubview(list)
        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.contentView.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay
        scroll.documentView = document
        scroll.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            list.leadingAnchor.constraint(equalTo: document.leadingAnchor), list.trailingAnchor.constraint(equalTo: document.trailingAnchor),
            list.topAnchor.constraint(equalTo: document.topAnchor), list.bottomAnchor.constraint(equalTo: document.bottomAnchor),
            scroll.heightAnchor.constraint(equalToConstant: height), scroll.widthAnchor.constraint(equalToConstant: width),
        ])
        return scroll
    }

    // MARK: Devices

    private func normalizedName(_ value: String) -> String { value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }

    private func symbol(forPeerName name: String) -> String {
        let lower = name.lowercased()
        let phones = ["phone", "pixel", "galaxy", "android", "oneplus", "xiaomi", "redmi", "samsung", "moto", "nothing", "huawei", "oppo", "vivo"]
        return phones.contains(where: { lower.contains($0) }) ? "iphone" : "laptopcomputer"
    }

    private func symbol(for device: TransferDevice) -> String {
        device.type.lowercased() == "mobile" ? "iphone" : "laptopcomputer"
    }

    private func lastSeenCaption(_ peer: PeerState, now: UInt64) -> (String, Bool) {
        guard peer.lastSeenMs > 0 else { return ("Paired", false) }
        guard now >= peer.lastSeenMs else { return ("Online", true) }
        let age = now - peer.lastSeenMs
        if age < 90_000 { return ("Online", true) }
        let minutes = age / 60_000
        if minutes < 60 { return ("Last seen \(max(1, minutes))m ago", false) }
        let hours = minutes / 60
        if hours < 24 { return ("Last seen \(hours)h ago", false) }
        return ("Last seen \(hours / 24)d ago", false)
    }

    private func renderList(_ stack: NSStackView, _ items: [CMRowItem], animated: Bool = true, make: @escaping (CMRowItem) -> NSView) {
        CMList.reconcile(stack, items, key: { $0.key }, animated: animated, make: { item in
            if item.placeholder { return CMEmptyRow(item.title, pulsing: item.pulsing) }
            let view = make(item)
            (view as? CMDeviceRow)?.configure(title: item.title, caption: item.caption, symbol: item.symbol, online: item.online, captionColor: item.captionColor)
            return view
        }, update: { view, item in
            if let empty = view as? CMEmptyRow { empty.set(item.title, pulsing: item.pulsing) }
            (view as? CMDeviceRow)?.configure(title: item.title, caption: item.caption, symbol: item.symbol, online: item.online, captionColor: item.captionColor)
        })
    }

    private func updateSeparators(_ stack: NSStackView) {
        var first = true
        for view in stack.arrangedSubviews where !CMList.isLeaving(view) {
            guard let row = view as? CMDeviceRow else { continue }
            row.showsSeparator = !first
            first = false
        }
    }

    private func renderPeers(_ peers: [PeerState], animated: Bool = true) {
        guard peersStack != nil else { return }
        let now = UInt64(max(0, Date().timeIntervalSince1970 * 1000))
        let sorted = peers.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        var items: [CMRowItem] = sorted.prefix(8).map { peer in
            let (caption, online) = lastSeenCaption(peer, now: now)
            return CMRowItem(key: "peer-" + peer.id, title: peer.name, caption: caption, symbol: symbol(forPeerName: peer.name), online: online,
                             captionColor: online ? CMColor.positive : CMColor.textMuted)
        }
        if peers.isEmpty { items = [CMRowItem(key: "__empty", title: "No paired devices yet. Press + to pair.", placeholder: true)] }
        if peers.count > 8 { items.append(CMRowItem(key: "__more", title: "+\(peers.count - 8) more devices", placeholder: true)) }
        renderList(peersStack, items, animated: animated) { [weak self] item in
            let row = CMDeviceRow()
            let id = String(item.key.dropFirst("peer-".count))
            let remove = CMPillButton("", symbol: "trash", style: .plain, height: 28) { [weak self] in self?.removePeer(id) }
            remove.tint = CMColor.textFaint
            remove.hoverTint = CMColor.negative
            remove.toolTip = "Remove"
            row.trailing.addArrangedSubview(remove)
            return row
        }
        updateSeparators(peersStack)
        armPeerStatusTimer(peers, now: now)
    }

    /// One one-shot timer for the soonest Online → "Last seen" transition (no polling).
    private func armPeerStatusTimer(_ peers: [PeerState], now: UInt64) {
        peerStatusWork?.cancel()
        peerStatusWork = nil
        guard window?.isVisible == true else { return }
        let next = peers.compactMap { peer -> UInt64? in
            guard peer.lastSeenMs > 0, now >= peer.lastSeenMs, now - peer.lastSeenMs < 90_000 else { return nil }
            return peer.lastSeenMs + 90_000
        }.min()
        guard let next else { return }
        let work = DispatchWorkItem { [weak self] in
            guard let self, let peers = self.latestState?.peers else { return }
            self.renderPeers(peers)
        }
        peerStatusWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + Double(next - now) / 1000 + 0.25, execute: work)
    }

    private func refreshDevicesPressed() {
        CMMotion.spin(devicesRefreshButton)
        LocalTransferManager.shared.discoverNow()
        refreshHome()
        refreshNearbyPairDevices()
    }

    private func nearbyDevicesChanged() {
        guard window?.isVisible == true else { return }
        if selectedTab == 0 { refreshNearbyPairDevices() }
        if selectedTab == 1 { refreshTransferDevices() }
    }

    private func refreshNearbyPairDevices() {
        guard nearbyPairStack != nil else { return }
        let pairedNames = Set((latestState?.peers ?? []).map { normalizedName($0.name) })
        let devices = LocalTransferManager.shared.nearbyDevices().filter { !pairedNames.contains(normalizedName($0.alias)) };
        var items = devices.map { device in
            CMRowItem(key: "nearby-" + device.fingerprint, title: device.alias, caption: device.model.isEmpty ? device.type.capitalized : device.model, symbol: symbol(for: device))
        }
        items.insert(CMRowItem(key: "__header", title: "Nearby", placeholder: true), at: 0)
        renderList(nearbyPairStack, items) { [weak self] item in
            let row = CMDeviceRow()
            let fingerprint = String(item.key.dropFirst("nearby-".count))
            row.trailing.addArrangedSubview(CMPillButton("Pair", style: .primary, height: 28) { [weak self] in
                guard let device = LocalTransferManager.shared.nearbyDevices().first(where: { $0.fingerprint == fingerprint }) else {
                    self?.toast("That device is no longer nearby", kind: .error)
                    return
                }
                self?.startNearbyPair(device)
            })
            return row
        }
        updateSeparators(nearbyPairStack)
        CMList.setVisible(nearbyPairStack, !devices.isEmpty, animated: true)
    }

    private func removePeer(_ id: String) {
        let name = latestState?.peers.first(where: { $0.id == id })?.name ?? "this device"
        guard CMDialog.confirmDestructive(title: "Remove \(name)?", message: "It stops syncing with this Mac until you pair again.", action: "Remove") else { return }
        if mutateRuntime({ try Runtime.forgetPeer(id) }) { toast("Removed \(name)", kind: .success) }
    }

    private func startNearbyPair(_ device: TransferDevice) {
        do {
            let credential = try Runtime.pairingLink()
            toast("Waiting for \(device.alias)…")
            NearbyPairingManager.shared.pair(credential: credential, with: device, code: { [weak self] value in
                self?.showNearbyPairCode(value, device: device.alias)
            }, completion: { [weak self] result in
                guard let self else { return }
                self.dismissNearbyPairCode()
                switch result {
                case .success:
                    self.toast("Paired with \(device.alias)", kind: .success)
                    LocalTransferManager.shared.discoverNow()
                    self.refreshHome()
                    self.refreshNearbyPairDevices()
                case .failure(let error):
                    self.showError(error.localizedDescription)
                    self.refreshHome()
                }
            })
        } catch { showError(error.localizedDescription) }
    }

    private func showNearbyPairCode(_ value: String, device: String) {
        dismissNearbyPairCode()

        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 452, height: 276),
            styleMask: [.titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.title = "ClipMesh"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isMovableByWindowBackground = true
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.backgroundColor = CMColor.surface

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 8
        root.edgeInsets = NSEdgeInsets(top: 28, left: 24, bottom: 24, right: 24)
        root.translatesAutoresizingMaskIntoConstraints = false

        let heading = NSTextField(labelWithString: "Verification code")
        heading.font = CMFont.semibold(18)
        heading.textColor = CMColor.text
        root.addArrangedSubview(heading)

        let detail = NSTextField(wrappingLabelWithString: "Enter this code on \(device).")
        detail.font = CMFont.regular(14)
        detail.textColor = CMColor.textMuted
        detail.preferredMaxLayoutWidth = 404
        root.addArrangedSubview(detail)
        root.setCustomSpacing(18, after: detail)

        let codeBox = NSView()
        codeBox.wantsLayer = true
        codeBox.layer?.cornerRadius = 16
        codeBox.layer?.backgroundColor = CMColor.fill05.cgColor
        codeBox.layer?.borderWidth = 1
        codeBox.layer?.borderColor = CMColor.line.cgColor
        codeBox.translatesAutoresizingMaskIntoConstraints = false

        let code = NSTextField(labelWithString: value)
        code.font = .monospacedDigitSystemFont(ofSize: 46, weight: .bold)
        code.textColor = CMColor.text
        code.alignment = .center
        code.maximumNumberOfLines = 1
        code.lineBreakMode = .byClipping
        code.translatesAutoresizingMaskIntoConstraints = false
        codeBox.addSubview(code)

        NSLayoutConstraint.activate([
            codeBox.widthAnchor.constraint(equalToConstant: 404),
            codeBox.heightAnchor.constraint(equalToConstant: 86),
            code.leadingAnchor.constraint(equalTo: codeBox.leadingAnchor, constant: 16),
            code.trailingAnchor.constraint(equalTo: codeBox.trailingAnchor, constant: -16),
            code.centerYAnchor.constraint(equalTo: codeBox.centerYAnchor),
        ])
        root.addArrangedSubview(codeBox)
        root.setCustomSpacing(14, after: codeBox)

        let waiting = NSTextField(labelWithString: "Waiting for confirmation…")
        waiting.font = CMFont.medium(12)
        waiting.textColor = CMColor.textMuted
        waiting.wantsLayer = true
        root.addArrangedSubview(waiting)

        panel.contentView = NSView()
        panel.contentView?.wantsLayer = true
        panel.contentView?.layer?.backgroundColor = CMColor.surface.cgColor
        panel.contentView?.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: panel.contentView!.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: panel.contentView!.trailingAnchor),
            root.topAnchor.constraint(equalTo: panel.contentView!.topAnchor),
            root.bottomAnchor.constraint(equalTo: panel.contentView!.bottomAnchor),
        ])
        CMMotion.pulse(waiting.layer, enabled: true)

        nearbyCodePanel = panel
        NSApp.activate(ignoringOtherApps: true)
        if let window {
            window.beginSheet(panel)
        } else {
            panel.center()
            panel.makeKeyAndOrderFront(nil)
        }
    }

    private func dismissNearbyPairCode() {
        guard let panel = nearbyCodePanel else { return }
        nearbyCodePanel = nil
        if let parent = panel.sheetParent { parent.endSheet(panel) }
        else { panel.orderOut(nil) }
    }

    private func approveNearbyPair(_ sender: String) -> Bool {
        var accepted = false
        let work = { accepted = CMDialog.run(title: "Pairing request", message: "\(sender) wants to pair with this Mac for encrypted clipboard sync.", buttons: ["Reject", "Accept"]) == 1 }
        if Thread.isMainThread { work() } else { DispatchQueue.main.sync(execute: work) }
        return accepted
    }

    private func promptNearbyCode(_ sender: String, submit: @escaping (String?) -> Void) {
        DispatchQueue.main.async {
            let input = NSTextField(string: "")
            input.alignment = .center
            input.font = .monospacedDigitSystemFont(ofSize: 34, weight: .bold)
            input.frame = NSRect(x: 0, y: 0, width: 280, height: 52)
            input.placeholderString = "6-digit code"
            submit(CMDialog.run(title: "Verify \(sender)", message: "Type the six-digit code shown on \(sender).", accessory: input, buttons: ["Cancel", "Pair"]) == 1 ? input.stringValue : nil)
        }
    }

    private func acceptNearbyCredential(_ uri: String, sender: String) -> Bool {
        var ok = false
        let work = {
            self.stopDaemon()
            do { try Runtime.join(uri, name: self.latestState?.deviceName ?? Runtime.deviceName()); try self.startDaemon(); self.refreshHome(); ok = true }
            catch { try? self.startDaemon(); self.showError(error.localizedDescription) }
        }
        if Thread.isMainThread { work() } else { DispatchQueue.main.sync(execute: work) }
        return ok
    }

    // MARK: Transfer

    private func transferState(for device: TransferDevice) -> CMTransferRow.State {
        if sendingFingerprint == device.fingerprint { return .sending(sendProgressValue) }
        if sentFingerprint == device.fingerprint { return .sent }
        return .idle(enabled: sendingFingerprint == nil)
    }

    private func transferRow(_ fingerprint: String) -> CMTransferRow? {
        transferDeviceStack?.arrangedSubviews.first { CMList.key(of: $0) == fingerprint } as? CMTransferRow
    }

    /// "Sending 2 of 3 · 41%", "Waiting for approval…", "Sent", or "Model · Trusted".
    private func transferCaption(for device: TransferDevice, favorite: Bool) -> (String, NSColor) {
        switch transferState(for: device) {
        case .sending(let value):
            let percent = Int((value * 100).rounded())
            if sendCaption.hasPrefix("Waiting") { return ("Waiting for \(device.alias) to accept…", CMColor.textMuted) }
            if let match = sendCaption.range(of: #"(\d+)/(\d+)$"#, options: .regularExpression) {
                let parts = sendCaption[match].split(separator: "/")
                if parts.count == 2, parts[1] != "1" { return ("Sending \(parts[0]) of \(parts[1]) · \(percent)%", CMColor.textSoft) }
                return ("Sending · \(percent)%", CMColor.textSoft)
            }
            return (sendCaption.isEmpty ? "Connecting…" : sendCaption, CMColor.textMuted)
        case .sent:
            return ("Sent", CMColor.positive)
        case .idle:
            let model = device.model.isEmpty ? device.type.capitalized : device.model
            return (favorite ? model + " · Trusted" : model, CMColor.textMuted)
        }
    }

    private func applyTransferRow(_ row: CMTransferRow, _ device: TransferDevice) {
        let favorite = LocalTransferManager.shared.isFavorite(device.fingerprint)
        let (caption, color) = transferCaption(for: device, favorite: favorite)
        row.configure(title: device.alias, caption: caption, symbol: symbol(for: device), online: false, captionColor: color)
        row.apply(favorite: favorite, state: transferState(for: device))
    }

    private func refreshTransferDevices() {
        guard transferDeviceStack != nil else { return }
        let devices = LocalTransferManager.shared.nearbyDevices();
        if devices.isEmpty {
            CMList.reconcile(transferDeviceStack, ["__empty"], key: { $0 }, animated: true, make: { _ in
                CMEmptyRow("Looking for devices on this network…", pulsing: true)
            }, update: { _, _ in })
            return
        }
        CMList.reconcile(transferDeviceStack, devices, key: { $0.fingerprint }, animated: true, make: { [weak self] device in
            let row = CMTransferRow()
            let fingerprint = device.fingerprint
            row.onSend = { [weak self] in
                guard let self else { return }
                guard let current = LocalTransferManager.shared.nearbyDevices().first(where: { $0.fingerprint == fingerprint }) else {
                    self.toast("That device is no longer nearby", kind: .error)
                    return
                }
                self.sendTransfer(to: current)
            }
            row.onFavorite = { [weak self] in
                LocalTransferManager.shared.setFavorite(fingerprint, !LocalTransferManager.shared.isFavorite(fingerprint))
                self?.refreshTransferDevices()
            }
            self?.applyTransferRow(row, device)
            return row
        }, update: { [weak self] view, device in
            if let row = view as? CMTransferRow { self?.applyTransferRow(row, device) }
        })
        updateSeparators(transferDeviceStack)
    }

    private func sendTransfer(to device: TransferDevice) {
        if transferFiles.isEmpty { chooseTransferFiles(); return }
        guard sendingFingerprint == nil else { return }
        let files = transferFiles
        sendingFingerprint = device.fingerprint
        sentFingerprint = nil
        sendProgressValue = 0
        sendCaption = "Connecting…"
        refreshTransferDevices()
        LocalTransferManager.shared.send(files: files, to: device, progress: { [weak self] text in
            guard let self, self.sendingFingerprint == device.fingerprint else { return }
            self.sendCaption = text
            if let row = self.transferRow(device.fingerprint) { self.applyTransferRow(row, device) }
        }, progressValue: { [weak self] value in
            guard let self, self.sendingFingerprint == device.fingerprint else { return }
            self.sendProgressValue = value
            if let row = self.transferRow(device.fingerprint) { self.applyTransferRow(row, device) }
        }) { [weak self] result in
            guard let self else { return }
            self.sendingFingerprint = nil
            self.sendCaption = ""
            CMTransferFeedback.clearDock()
            switch result {
            case .success:
                let count = files.count
                let summary = "Sent \(count) file\(count == 1 ? "" : "s") to \(device.alias)"
                self.sentFingerprint = device.fingerprint
                let sent = Set(files.map { $0.standardizedFileURL.path })
                let remaining = self.transferFiles.filter { !sent.contains($0.standardizedFileURL.path) }
                if remaining.isEmpty {
                    self.clearTransferSelection(animated: true)
                } else {
                    self.transferFiles = remaining
                    self.updateTransferSelection(animated: true)
                }
                self.toast(summary, kind: .success)
                if !NSApp.isActive { CMTransferFeedback.notify(title: "File sent", body: summary) }
                CMMotion.after(2.4) { [weak self] in
                    guard let self, self.sentFingerprint == device.fingerprint else { return }
                    self.sentFingerprint = nil
                    self.refreshTransferDevices()
                }
                self.refreshTransferDevices()
            case .failure(let error):
                self.refreshTransferDevices()
                if !NSApp.isActive { CMTransferFeedback.notify(title: "Transfer failed", body: error.localizedDescription) }
                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)
            }
        }
    }

    private func clearTransferSelection(animated: Bool) {
        transferFiles.removeAll()
        updateTransferSelection(animated: animated)
    }

    private func addTransferFiles(_ urls: [URL]) {
        let expanded = CMShareIntake.expand(urls)
        guard !expanded.isEmpty else {
            if !urls.isEmpty { toast("Nothing to send in that selection", kind: .error) }
            return
        }
        var seen = Set(transferFiles.map { $0.standardizedFileURL.path })
        for url in expanded where seen.insert(url.standardizedFileURL.path).inserted { transferFiles.append(url) }
        updateTransferSelection(animated: true)
        LocalTransferManager.shared.discoverNow()
        refreshTransferDevices()
    }

    private func updateTransferSelection(animated: Bool) {
        guard transferFilesStack != nil, dropZone != nil else { return }
        let empty = transferFiles.isEmpty
        if empty {
            let clearTiles = { [weak self] in
                guard let self, self.transferFiles.isEmpty else { return }
                CMList.reconcile(self.transferFilesStack, [String](), key: { $0 }, animated: false, make: { _ in NSView() }, update: { _, _ in })
                CMList.setVisible(self.dropZone, true, animated: animated)
            }
            if animated && !filesPanel.isHidden && window?.isVisible == true {
                CMList.setVisible(filesPanel, false, animated: true)
                CMMotion.after(0.32, clearTiles)
            } else {
                CMList.setVisible(filesPanel, false, animated: false)
                clearTiles()
            }
            return
        }
        let total = transferFiles.reduce(Int64(0)) { sum, url in sum + Int64((try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0) }
        filesSummaryLabel.stringValue = "\(transferFiles.count) file\(transferFiles.count == 1 ? "" : "s") · \(cmByteString(total))"
        let wasHidden = filesPanel.isHidden
        if wasHidden {
            CMList.setVisible(dropZone, false, animated: false)
            CMList.setVisible(filesPanel, true, animated: animated)
        }
        let limit = 60
        var keys = transferFiles.prefix(limit).map { $0.standardizedFileURL.path }
        if transferFiles.count > limit { keys.append("__more") }
        let overflow = transferFiles.count - limit
        CMList.reconcile(transferFilesStack, keys, key: { $0 }, animated: animated && !wasHidden, make: { [weak self] key in
            if key == "__more" { return CMFileTile(url: nil, moreCount: overflow) }
            let tile = CMFileTile(url: URL(fileURLWithPath: key))
            tile.onRemove = { [weak self] in
                guard let self else { return }
                self.transferFiles.removeAll { $0.standardizedFileURL.path == key }
                self.updateTransferSelection(animated: true)
            }
            return tile
        }, update: { _, _ in })
    }

    private func chooseTransferFiles() {
        guard let window, window.attachedSheet == nil else { return }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.prompt = "Choose"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK else { return }
            self?.addTransferFiles(panel.urls)
        }
    }

    /// Finder Share extension, Services, status menu and drag and drop all land here.
    private func receiveSharedFiles(_ urls: [URL]) {
        guard window != nil, pages.count == 3 else { pendingSharedFiles += urls; return }
        showWindow()
        selectTab(1, animated: true)
        addTransferFiles(urls)
    }

    private func showIncomingTransferProgress(sender: String, file: String, fraction: Double, complete: Bool) {
        if fraction < 0 {
            statusItem?.length = NSStatusItem.squareLength
            statusItem?.button?.title = ""
            statusItem?.button?.toolTip = nil
            showIncomingBanner("Couldn’t receive \(file) from \(sender)", state: .failed, hideAfter: 4)
            return
        }
        let percent = Int((min(1, max(0, fraction)) * 100).rounded())
        if complete {
            statusItem?.length = NSStatusItem.squareLength
            statusItem?.button?.title = ""
            statusItem?.button?.toolTip = nil
            showIncomingBanner("Received from \(sender)", state: .done, hideAfter: 3)
        } else {
            statusItem?.length = NSStatusItem.variableLength
            statusItem?.button?.title = " ↓ \(percent)%"
            statusItem?.button?.toolTip = "Receiving \(file) from \(sender)"
            showIncomingBanner("Receiving \(file) from \(sender)", state: .progress, fraction: min(1, max(0, fraction)))
        }
    }

    private func showIncomingBanner(_ text: String, state: CMBanner.State, fraction: Double = 0, hideAfter: TimeInterval? = nil) {
        guard let incomingBanner else { return }
        incomingHideToken += 1
        let token = incomingHideToken
        guard window?.isVisible == true else { incomingBanner.isHidden = true; return }
        incomingBanner.show(text, state: state, fraction: fraction)
        CMList.setVisible(incomingBanner, true, animated: true)
        guard let hideAfter else { return }
        CMMotion.after(hideAfter) { [weak self] in
            guard let self, self.incomingHideToken == token else { return }
            CMList.setVisible(incomingBanner, false, animated: true)
        }
    }

    // MARK: Settings

    private func syncSwitchChanged() {
        let send = sendToggle.isOn, receive = receiveToggle.isOn
        mutateRuntime { try Runtime.setSync(send: send, receive: receive) }
    }

    private func syncSettingsControls() {
        if latestState == nil, let state = try? Runtime.uiState() { latestState = state }
        guard let state = latestState else { return }
        let animated = window?.isVisible == true && selectedTab == 2
        sendToggle?.setOn(state.sendEnabled, animated: animated)
        receiveToggle?.setOn(state.receiveEnabled, animated: animated)
        deviceNameValue?.stringValue = state.deviceName
        deviceIDValue?.stringValue = state.deviceID
        for line in deviceLines where line.stringValue != "This device · \(state.deviceName)" { line.stringValue = "This device · \(state.deviceName)" }
        receiveFolderValue?.stringValue = LocalTransferManager.shared.outputFolderURL.path
    }

    private func chooseOutputFolder() {
        let panel = NSOpenPanel()
        panel.title = "Choose ClipMesh receive folder"
        panel.prompt = "Use Folder"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = LocalTransferManager.shared.outputFolderURL
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try LocalTransferManager.shared.setOutputFolder(url)
            receiveFolderValue?.stringValue = LocalTransferManager.shared.outputFolderURL.path
            toast("Files will be saved to \(LocalTransferManager.shared.outputFolderURL.lastPathComponent)", kind: .success)
        }
        catch { showError(error.localizedDescription) }
    }

    private static let shareExtensionID = "dev.clipmesh.private.Share"

    private static func pluginkit(_ arguments: [String]) -> (status: Int32, output: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pluginkit")
        process.arguments = arguments
        let out = Pipe()
        process.standardOutput = out
        process.standardError = Pipe()
        do { try process.run() } catch { return (-1, "") }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    private func setShareStatus(_ enabled: Bool?) {
        guard let label = shareStatusValue else { return }
        switch enabled {
        case .some(true): label.stringValue = "Enabled"; label.textColor = CMColor.positive
        case .some(false): label.stringValue = "Not enabled · Finder › Share › Edit Extensions"; label.textColor = CMColor.textMuted
        case .none: label.stringValue = "Not included in this build"; label.textColor = CMColor.textMuted
        }
    }

    private func refreshShareExtensionStatus() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let output = Self.pluginkit(["-m", "-i", Self.shareExtensionID]).output
            let line = output.trimmingCharacters(in: .whitespacesAndNewlines)
            DispatchQueue.main.async { self?.setShareStatus(line.isEmpty ? false : line.hasPrefix("+")) }
        }
    }

    private func registerShareExtension(showResult: Bool = false) {
        guard let plugIns = Bundle.main.builtInPlugInsURL else { setShareStatus(nil); return }
        let appex = plugIns.appendingPathComponent("ClipMeshShare.appex")
        guard FileManager.default.fileExists(atPath: appex.path) else { setShareStatus(nil); return }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            _ = Self.pluginkit(["-a", appex.path])
            _ = Self.pluginkit(["-e", "use", "-i", Self.shareExtensionID])
            let line = Self.pluginkit(["-m", "-i", Self.shareExtensionID]).output.trimmingCharacters(in: .whitespacesAndNewlines)
            let enabled = line.hasPrefix("+")
            DispatchQueue.main.async {
                NSUpdateDynamicServices()
                self?.setShareStatus(enabled)
                guard showResult else { return }
                if enabled { self?.toast("Share extension is on. Find it under Share in Finder.", kind: .success) }
                else { self?.toast("Turn on ClipMesh in Finder › Share › Edit Extensions") }
            }
        }
    }

    // MARK: Status item

    private func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let image = NSImage(systemSymbolName: "arrow.left.arrow.right", accessibilityDescription: "ClipMesh") {
            image.isTemplate = true
            item.button?.image = image
        }
        item.button?.target = self
        item.button?.action = #selector(statusItemClicked(_:))
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])

        let menu = NSMenu()
        let show = NSMenuItem(title: "Show ClipMesh", action: #selector(showFromMenu), keyEquivalent: "")
        show.target = self
        menu.addItem(show)
        let pair = NSMenuItem(title: "Copy Pairing Code", action: #selector(copyPairingLink), keyEquivalent: "")
        pair.target = self
        menu.addItem(pair)
        let send = NSMenuItem(title: "Send Files…", action: #selector(sendFiles), keyEquivalent: "")
        send.target = self
        menu.addItem(send)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusMenu = menu
        statusItem = item
    }

    // MARK: Daemon

    private func setSync(_ health: SyncHealth, detail: String? = nil) {
        switch health {
        case .starting: statusPill?.set("Starting…", color: CMColor.textMuted, pulse: true)
        case .on: statusPill?.set("Sync on", color: CMColor.positive)
        case .recovering: statusPill?.set("Recovering…", color: CMColor.accent, pulse: true)
        case .stopped: statusPill?.set("Sync stopped", color: CMColor.negative)
        }
        statusPill?.toolTip = detail
    }

    private func scheduleDaemonRestart(after terminationStatus: Int32) {
        guard !quitting else { return }
        daemonRestartWorkItem?.cancel()
        daemonRestartAttempts += 1
        let attempt = daemonRestartAttempts
        guard attempt <= 4 else {
            setSync(.stopped, detail: "Background sync could not recover (exit \(terminationStatus))")
            showWindow()
            toast("Background sync could not recover (exit \(terminationStatus))", kind: .error)
            return
        }
        let delays: [TimeInterval] = [0.35, 0.8, 1.6, 3.0]
        let work = DispatchWorkItem { [weak self] in
            guard let self, !self.quitting else { return }
            do {
                try self.startDaemon()
            } catch {
                self.setSync(.recovering, detail: "Background sync recovery \(attempt)/4 failed")
                self.scheduleDaemonRestart(after: terminationStatus)
            }
        }
        daemonRestartWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delays[min(attempt - 1, delays.count - 1)], execute: work)
    }

    private func startDaemon() throws {
        try FileManager.default.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
        // A force-quit or UI crash can orphan clipmesh-bin. Reclaim only an
        // executable positively identified as ClipMesh; never kill by port alone.
        try Runtime.reclaimStaleDaemonListener()
        if !FileManager.default.fileExists(atPath: Runtime.log.path) {
            FileManager.default.createFile(atPath: Runtime.log.path, contents: nil)
        }
        if logHandle == nil {
            let handle = try FileHandle(forWritingTo: Runtime.log)
            handle.seekToEndOfFile()
            logHandle = handle
        }

        let process = Process()
        process.executableURL = Runtime.cli
        process.arguments = ["run"]
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self, weak process] ended in
            DispatchQueue.main.async {
                guard let self, let process, !self.quitting, self.daemon === process else { return }
                self.daemon = nil
                self.setSync(.recovering, detail: "Background sync was interrupted")
                self.scheduleDaemonRestart(after: ended.terminationStatus)
            }
        }
        try process.run()
        daemon = process
        var ready = false
        for _ in 0..<35 {
            if !process.isRunning { break }
            if Runtime.clipboardDaemonIsListening(process.processIdentifier) {
                ready = true
                break
            }
            usleep(100_000)
        }
        guard ready, process.isRunning else {
            if process.isRunning { process.terminate() }
            process.waitUntilExit()
            if daemon === process { daemon = nil }
            throw NSError(domain: "ClipMesh", code: Int(process.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: "ClipMesh background sync started but never became ready."
            ])
        }
        setSync(.on)
        daemonRestartWorkItem?.cancel()
        daemonRestartWorkItem = nil
        let stableProcess = process
        DispatchQueue.main.asyncAfter(deadline: .now() + 8.0) { [weak self, weak stableProcess] in
            guard let self, let stableProcess, self.daemon === stableProcess, stableProcess.isRunning else { return }
            self.daemonRestartAttempts = 0
        }
    }

    private func stopDaemon() {
        guard let process = daemon else { return }
        daemon = nil
        if process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
    }

    @discardableResult private func mutateRuntime(_ operation: () throws -> Void) -> Bool {
        stopDaemon()
        do {
            try operation()
            try startDaemon()
            refreshHome()
            return true
        } catch {
            try? startDaemon()
            showError(error.localizedDescription)
            return false
        }
    }

    /// Spawns `ui-state` — only at launch, after our own mutations, or on an explicit refresh.
    private func refreshHome() {
        do {
            applyState(try Runtime.uiState())
            diskStamp = currentDiskStamp()
        } catch {
            showError(error.localizedDescription)
        }
    }

    private func applyState(_ state: UIState) {
        latestState = state
        renderPeers(state.peers)
        if selectedTab == 0 { refreshNearbyPairDevices() }
        syncSettingsControls()
        if daemon?.isRunning == true { setSync(.on) }
    }

    private var peersFile: URL { Runtime.support.appendingPathComponent("peers.json") }

    private func currentDiskStamp() -> String {
        [Runtime.config, peersFile].map { url -> String in
            let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey])
            return "\(values?.contentModificationDate?.timeIntervalSince1970 ?? 0):\(values?.fileSize ?? -1)"
        }.joined(separator: "|")
    }

    /// Reads config.json + peers.json directly (written atomically by the daemon); no process spawn.
    private func loadDiskState() -> UIState? {
        guard let data = try? Data(contentsOf: Runtime.config),
              let config = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let deviceID = config["device_id"] as? String, let spaceID = config["space_id"] as? String
        else { return nil }
        var peers: [PeerState] = []
        if let peerData = try? Data(contentsOf: peersFile),
           let file = (try? JSONSerialization.jsonObject(with: peerData)) as? [String: Any],
           (file["schema"] as? NSNumber)?.intValue == 1,
           (file["space_id"] as? String)?.lowercased() == spaceID.lowercased(),
           let list = file["peers"] as? [[String: Any]] {
            for item in list {
                guard let id = item["device_id"] as? String else { continue }
                peers.append(PeerState(id: id, name: (item["name"] as? String) ?? "Device", lastSeenMs: (item["last_seen_ms"] as? NSNumber)?.uint64Value ?? 0))
            }
        }
        return UIState(
            deviceID: deviceID,
            deviceName: (config["device_name"] as? String) ?? (latestState?.deviceName ?? "Mac"),
            spaceID: spaceID,
            sendEnabled: (config["send_enabled"] as? Bool) ?? true,
            receiveEnabled: (config["receive_enabled"] as? Bool) ?? true,
            peers: peers
        )
    }

    private func reloadStateFromDisk() {
        let stamp = currentDiskStamp()
        guard stamp != diskStamp else { return }
        diskStamp = stamp
        if let state = loadDiskState() { applyState(state) }
    }

    private func startWatchingSupport() {
        if supportWatcher == nil {
            supportWatcher = CMDirectoryWatcher(url: Runtime.support) { [weak self] in self?.reloadStateFromDisk() }
        }
        supportWatcher?.start()
    }

    private func showWindow() {
        LocalTransferManager.shared.setUIVisible(true)
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if latestState != nil { diskStamp = ""; reloadStateFromDisk() }
        startWatchingSupport()
        if selectedTab == 0 { refreshNearbyPairDevices(); refreshClipboardPreview() }
        if selectedTab == 1 { refreshTransferDevices() }
    }

    private func hideWindow() {
        LocalTransferManager.shared.setUIVisible(false)
        supportWatcher?.stop()
        peerStatusWork?.cancel(); peerStatusWork = nil
        window?.orderOut(nil)
        NSApp.setActivationPolicy(.accessory)
    }

    private func toast(_ text: String, kind: CMToast.Kind = .info) {
        CMToast.show(text, kind: kind, in: window?.contentView)
    }

    private func showError(_ message: String) {
        showWindowWithoutRefresh()
        let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        toast(text.isEmpty ? "Something went wrong" : text, kind: .error)
    }

    private func showWindowWithoutRefresh() {
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func statusItemClicked(_ sender: Any?) {
        guard let event = NSApp.currentEvent else { return }
        if event.type == .rightMouseUp {
            if let button = statusItem?.button, let menu = statusMenu {
                menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
            }
        } else {
            showWindow()
        }
    }

    @objc private func showFromMenu() { showWindow() }

    @objc private func sendFiles() {
        showWindow()
        selectTab(1, animated: true)
        chooseTransferFiles()
    }

    @objc func shareFiles(_ pasteboard: NSPasteboard, userData: String, error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        let urls = (pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        guard !urls.isEmpty else {
            error.pointee = "Select one or more files in Finder first." as NSString
            return
        }
        receiveSharedFiles(urls)
    }

    // MARK: Actions

    private func renameDevice() {
        let input = NSTextField(string: latestState?.deviceName ?? Runtime.deviceName()); input.placeholderString = "Device name"
        guard CMDialog.run(title: "Rename this device", message: "Shown to your other devices.", accessory: input, buttons: ["Cancel", "Save"]) == 1 else { return }
        let name = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name != latestState?.deviceName else { return }
        if mutateRuntime({ try Runtime.setName(name) }) { toast("Renamed to \(name)", kind: .success) }
    }

    private func pairWithCode() {
        let input = NSTextField(string: "")
        input.placeholderString = "clipmesh://pair?…"
        input.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        guard CMDialog.run(title: "Pair with a code", message: "Paste the pairing code copied on your other device.", accessory: input, buttons: ["Cancel", "Pair"]) == 1 else { return }
        let uri = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !uri.isEmpty else { showError("Paste a ClipMesh pairing code first."); return }
        if !(latestState?.peers.isEmpty ?? true) {
            guard confirmSpaceReplacement(title: "Join this private space?") else { return }
        }
        let name = latestState?.deviceName ?? Runtime.deviceName()
        if mutateRuntime({ try Runtime.join(uri, name: name) }) { toast("Joined the private space", kind: .success) }
    }

    @objc private func copyPairingLink() {
        do {
            let link = try Runtime.pairingLink()
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(link, forType: .string)
            refreshClipboardPreview()
            toast("Pairing code copied. Treat it like a password.", kind: .success)
        } catch {
            showError(error.localizedDescription)
        }
    }

    private func createNewSpace() {
        guard confirmSpaceReplacement(title: "Create a new private space?") else { return }
        let name = latestState?.deviceName ?? Runtime.deviceName()
        if mutateRuntime({ try Runtime.createNewSpace(name: name) }) { toast("New private space created", kind: .success) }
    }

    private func resetPairing() {
        guard CMDialog.confirmDestructive(title: "Reset all pairing?", message: "This creates a new device identity and private space, forgets every device, and every other device must pair again.", action: "Reset") else { return }
        let name = latestState?.deviceName ?? Runtime.deviceName()
        if mutateRuntime({ try Runtime.resetIdentity(name: name) }) { toast("Pairing reset", kind: .success) }
    }

    private func confirmSpaceReplacement(title: String) -> Bool {
        CMDialog.confirm(title: title, message: "This replaces this Mac's current ClipMesh space and known-device list.")
    }

    @objc private func quitApp() {
        quitting = true
        NearbyPairingManager.shared.stop()
        LocalTransferManager.shared.stop()
        stopDaemon()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
