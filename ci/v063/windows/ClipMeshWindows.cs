using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

// ClipMesh "Ember" UI for Windows (v063). C# 5 / .NET Framework 4.x only.

// ---------------------------------------------------------------------------
// Native helpers
// ---------------------------------------------------------------------------
internal static class EmberNative
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X, Y; public POINT(int x, int y) { X = x; Y = y; } }
    [StructLayout(LayoutKind.Sequential)]
    public struct SIZE { public int Cx, Cy; public SIZE(int cx, int cy) { Cx = cx; Cy = cy; } }
    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    public struct BLENDFUNCTION { public byte BlendOp, BlendFlags, SourceConstantAlpha, AlphaFormat; }

    [DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr hwnd, int attribute, out RECT value, int size);
    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)] public static extern int SetWindowTheme(IntPtr hwnd, string appName, string idList);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll", SetLastError = true)] public static extern bool AddClipboardFormatListener(IntPtr hwnd);
    [DllImport("user32.dll", SetLastError = true)] public static extern bool RemoveClipboardFormatListener(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern uint GetClipboardSequenceNumber();
    [DllImport("gdi32.dll")] public static extern IntPtr AddFontMemResourceEx(IntPtr font, uint length, IntPtr reserved, ref uint fonts);
    [DllImport("user32.dll", SetLastError = true)] public static extern bool UpdateLayeredWindow(IntPtr hwnd, IntPtr hdcDst, ref POINT pptDst, ref SIZE psize, IntPtr hdcSrc, ref POINT pprSrc, int crKey, ref BLENDFUNCTION pblend, int dwFlags);
    [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr hwnd, IntPtr hdc);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr hdc);
    [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr hdc, IntPtr obj);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr obj);
    [DllImport("user32.dll")] public static extern bool SystemParametersInfo(uint action, uint param, ref bool value, uint winIni);
    [DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(int processId);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool ReleaseCapture();
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam);

    public static void DarkChrome(IntPtr hwnd, bool roundCorners)
    {
        if (hwnd == IntPtr.Zero) return;
        try
        {
            int on = 1;
            if (DwmSetWindowAttribute(hwnd, 20, ref on, 4) != 0) DwmSetWindowAttribute(hwnd, 19, ref on, 4);
        }
        catch { }
        if (roundCorners)
        {
            try { int round = 2; DwmSetWindowAttribute(hwnd, 33, ref round, 4); } catch { }
        }
    }

    public static void DarkScrollbars(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return;
        try { SetWindowTheme(hwnd, "DarkMode_Explorer", null); } catch { }
    }

    // Visible frame (excludes the invisible DWM resize borders) in screen pixels.
    public static Rectangle VisibleFrame(Form form)
    {
        try
        {
            RECT r;
            if (form.IsHandleCreated && DwmGetWindowAttribute(form.Handle, 9, out r, Marshal.SizeOf(typeof(RECT))) == 0 && r.Right > r.Left)
                return Rectangle.FromLTRB(r.Left, r.Top, r.Right, r.Bottom);
        }
        catch { }
        return form.Bounds;
    }

    public static bool AnimationsEnabled()
    {
        try { bool value = true; if (SystemParametersInfo(0x1042, 0, ref value, 0)) return value; } catch { }
        return true;
    }
}

// ---------------------------------------------------------------------------
// Design tokens, fonts and drawing helpers
// ---------------------------------------------------------------------------
internal static class Ember
{
    public static readonly Color Bg = Color.FromArgb(0x13, 0x13, 0x14);
    public static readonly Color Surface = Color.FromArgb(0x22, 0x22, 0x22);
    public static readonly Color Accent = Color.FromArgb(0xE5, 0x5F, 0x11);
    public static readonly Color AccentPressed = Color.FromArgb(0xC9, 0x52, 0x0E);
    public static readonly Color AccentHover = Color.FromArgb(0xEC, 0x6C, 0x22);
    public static readonly Color AccentSoft = Color.FromArgb(36, 0xE5, 0x5F, 0x11);
    public static readonly Color Text = Color.White;
    public static readonly Color TextSoft = Color.FromArgb(0xDD, 0xDD, 0xDD);
    public static readonly Color TextMuted = Color.FromArgb(128, 255, 255, 255);
    public static readonly Color TextFaint = Color.FromArgb(89, 255, 255, 255);
    public static readonly Color Line = Color.FromArgb(20, 255, 255, 255);
    public static readonly Color Fill05 = Color.FromArgb(13, 255, 255, 255);
    public static readonly Color Fill06 = Color.FromArgb(15, 255, 255, 255);
    public static readonly Color Fill07 = Color.FromArgb(18, 255, 255, 255);
    public static readonly Color Fill12 = Color.FromArgb(31, 255, 255, 255);
    public static readonly Color Fill20 = Color.FromArgb(51, 255, 255, 255);
    public static readonly Color Positive = Color.FromArgb(0x3F, 0xD0, 0x5E);
    public static readonly Color Negative = Color.FromArgb(0xFF, 0x6B, 0x5A);
    public static readonly Color NegativeHover = Color.FromArgb(0xFF, 0x80, 0x71);
    public static readonly Color ToggleOff = Color.FromArgb(0x3A, 0x3A, 0x3A);

    public static float Scale = 1f;
    public static TextRenderingHint TextHint = TextRenderingHint.AntiAliasGridFit;
    private static bool initialized;
    private static readonly Dictionary<string, Font> fonts = new Dictionary<string, Font>();
    private static readonly PrivateFontCollection collection = new PrivateFontCollection();
    private static FontFamily soraRegular, soraMedium, soraSemiBold;
    private static string fallbackFamily = "Segoe UI";
    private static readonly Bitmap measureBitmap = new Bitmap(1, 1);
    private static Graphics measureGraphics;

    public static void Init()
    {
        if (initialized) return;
        initialized = true;
        try { using (Graphics g = Graphics.FromHwnd(IntPtr.Zero)) Scale = Math.Max(1f, g.DpiX / 96f); } catch { Scale = 1f; }
        Anim.ReduceMotion = !EmberNative.AnimationsEnabled();
        try { if (SystemInformation.IsFontSmoothingEnabled && SystemInformation.FontSmoothingType == 2) TextHint = TextRenderingHint.ClearTypeGridFit; } catch { }
        LoadFonts();
        foreach (string name in new string[] { "Segoe UI Variable Text", "Segoe UI" })
        {
            try { using (FontFamily f = new FontFamily(name)) { fallbackFamily = name; break; } } catch { }
        }
    }

    private static void LoadFonts()
    {
        string[] names = new string[] { "SoraRegular", "SoraMedium", "SoraSemiBold", "SoraBold" };
        Assembly assembly = Assembly.GetExecutingAssembly();
        foreach (string name in names)
        {
            try
            {
                using (Stream stream = assembly.GetManifestResourceStream("ClipMesh.Font." + name))
                {
                    if (stream == null) continue;
                    byte[] data = new byte[stream.Length];
                    int offset = 0;
                    while (offset < data.Length) { int read = stream.Read(data, offset, data.Length - offset); if (read <= 0) break; offset += read; }
                    // The memory must stay alive for the process lifetime (GDI+ and GDI both reference it).
                    IntPtr memory = Marshal.AllocCoTaskMem(data.Length);
                    Marshal.Copy(data, 0, memory, data.Length);
                    collection.AddMemoryFont(memory, data.Length);
                    uint count = 0;
                    try { EmberNative.AddFontMemResourceEx(memory, (uint)data.Length, IntPtr.Zero, ref count); } catch { }
                }
            }
            catch { }
        }
        try
        {
            foreach (FontFamily family in collection.Families)
            {
                string name = family.Name ?? "";
                if (!name.StartsWith("Sora", StringComparison.OrdinalIgnoreCase)) continue;
                if (name.IndexOf("SemiBold", StringComparison.OrdinalIgnoreCase) >= 0) soraSemiBold = family;
                else if (name.IndexOf("Medium", StringComparison.OrdinalIgnoreCase) >= 0) soraMedium = family;
                else if (name.Trim().Equals("Sora", StringComparison.OrdinalIgnoreCase)) soraRegular = family;
            }
        }
        catch { }
    }

    // Used by --ui-snapshot to render at several DPI-equivalent scales in one process.
    public static void SetScale(float scale)
    {
        Init();
        Scale = Math.Max(1f, scale);
        foreach (Font f in fonts.Values) { try { f.Dispose(); } catch { } }
        fonts.Clear();
    }

    public static int S(float value) { return (int)Math.Round(value * Scale); }
    public static float Sf(float value) { return value * Scale; }

    // weight: 400 regular, 500 medium, 600 semibold, 700 bold. size is in design pixels.
    public static Font Font(float size, int weight)
    {
        string key = size.ToString("0.0") + "/" + weight;
        Font font;
        if (fonts.TryGetValue(key, out font)) return font;
        float px = size * Scale;
        font = null;
        try
        {
            bool bold = soraRegular != null && soraRegular.IsStyleAvailable(FontStyle.Bold);
            if (weight >= 700 && bold) font = new Font(soraRegular, px, FontStyle.Bold, GraphicsUnit.Pixel);
            else if (weight >= 600 && soraSemiBold != null) font = new Font(soraSemiBold, px, FontStyle.Regular, GraphicsUnit.Pixel);
            else if (weight >= 600 && bold) font = new Font(soraRegular, px, FontStyle.Bold, GraphicsUnit.Pixel);
            else if (weight >= 500 && soraMedium != null) font = new Font(soraMedium, px, FontStyle.Regular, GraphicsUnit.Pixel);
            else if (soraRegular != null && soraRegular.IsStyleAvailable(FontStyle.Regular)) font = new Font(soraRegular, px, FontStyle.Regular, GraphicsUnit.Pixel);
        }
        catch { font = null; }
        if (font == null)
        {
            try
            {
                if (weight >= 700) font = new Font(fallbackFamily, px, FontStyle.Bold, GraphicsUnit.Pixel);
                else if (weight >= 600) font = TryFont(fallbackFamily == "Segoe UI" ? "Segoe UI Semibold" : "Segoe UI Variable Text Semibold", px, FontStyle.Regular) ?? new Font(fallbackFamily, px, FontStyle.Bold, GraphicsUnit.Pixel);
                else if (weight >= 500) font = TryFont(fallbackFamily == "Segoe UI" ? "Segoe UI Semibold" : "Segoe UI Variable Text Semibold", px, FontStyle.Regular) ?? new Font(fallbackFamily, px, FontStyle.Regular, GraphicsUnit.Pixel);
                else font = new Font(fallbackFamily, px, FontStyle.Regular, GraphicsUnit.Pixel);
            }
            catch { font = new Font(FontFamily.GenericSansSerif, px, FontStyle.Regular, GraphicsUnit.Pixel); }
        }
        fonts[key] = font;
        return font;
    }

    public static Font Mono(float size)
    {
        string key = "mono/" + size.ToString("0.0");
        Font font;
        if (fonts.TryGetValue(key, out font)) return font;
        float px = size * Scale;
        font = TryFont("Cascadia Mono", px, FontStyle.Regular) ?? TryFont("Consolas", px, FontStyle.Regular) ?? new Font(FontFamily.GenericMonospace, px, FontStyle.Regular, GraphicsUnit.Pixel);
        fonts[key] = font;
        return font;
    }

    private static Font TryFont(string family, float px, FontStyle style)
    {
        try
        {
            using (FontFamily f = new FontFamily(family))
            {
                if (!f.IsStyleAvailable(style)) return null;
                return new Font(family, px, style, GraphicsUnit.Pixel);
            }
        }
        catch { return null; }
    }

    // ----- colors -----
    public static Color Mix(Color a, Color b, double t)
    {
        if (t <= 0) return a; if (t >= 1) return b;
        return Color.FromArgb(
            (int)Math.Round(a.A + (b.A - a.A) * t), (int)Math.Round(a.R + (b.R - a.R) * t),
            (int)Math.Round(a.G + (b.G - a.G) * t), (int)Math.Round(a.B + (b.B - a.B) * t));
    }

    // Composites a (possibly translucent) color over an opaque background.
    public static Color Over(Color fg, Color bg)
    {
        double a = fg.A / 255.0;
        return Color.FromArgb(255,
            (int)Math.Round(fg.R * a + bg.R * (1 - a)), (int)Math.Round(fg.G * a + bg.G * (1 - a)), (int)Math.Round(fg.B * a + bg.B * (1 - a)));
    }

    // Opaque color for fg drawn on bg, faded towards bg by alpha (0..1).
    public static Color Ink(Color fg, Color bg, double alpha)
    {
        Color solid = Over(fg, Color.FromArgb(255, bg));
        return alpha >= 1 ? solid : Mix(Color.FromArgb(255, bg), solid, Math.Max(0, alpha));
    }

    // ----- geometry -----
    public static GraphicsPath Round(RectangleF r, float radius)
    {
        GraphicsPath path = new GraphicsPath();
        float d = Math.Min(radius * 2, Math.Min(r.Width, r.Height));
        if (d <= 0.5f) { path.AddRectangle(r); return path; }
        path.AddArc(r.X, r.Y, d, d, 180, 90);
        path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }

    public static RectangleF ScaleAround(RectangleF r, float s)
    {
        if (Math.Abs(s - 1f) < 0.001f) return r;
        float w = r.Width * s, h = r.Height * s;
        return new RectangleF(r.X + (r.Width - w) / 2f, r.Y + (r.Height - h) / 2f, w, h);
    }

    public static void Fill(Graphics g, RectangleF r, float radius, Color color)
    {
        if (color.A == 0 || r.Width <= 0 || r.Height <= 0) return;
        using (GraphicsPath p = Round(r, radius)) using (SolidBrush b = new SolidBrush(color)) g.FillPath(b, p);
    }

    public static void Stroke(Graphics g, RectangleF r, float radius, Color color, float width)
    {
        if (color.A == 0 || r.Width <= 1 || r.Height <= 1) return;
        RectangleF inset = new RectangleF(r.X + width / 2f, r.Y + width / 2f, r.Width - width, r.Height - width);
        using (GraphicsPath p = Round(inset, Math.Max(0, radius - width / 2f))) using (Pen pen = new Pen(color, width)) g.DrawPath(pen, p);
    }

    public static void Prepare(Graphics g)
    {
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.PixelOffsetMode = PixelOffsetMode.HighQuality;
        g.TextRenderingHint = TextHint;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.CompositingQuality = CompositingQuality.HighQuality;
    }

    // ----- text -----
    private static StringFormat Format(StringAlignment h, StringAlignment v, bool wrap, StringTrimming trimming)
    {
        StringFormat f = new StringFormat(StringFormat.GenericTypographic);
        f.Alignment = h; f.LineAlignment = v; f.Trimming = trimming;
        f.FormatFlags = (wrap ? 0 : StringFormatFlags.NoWrap) | StringFormatFlags.MeasureTrailingSpaces;
        if (!wrap) f.FormatFlags |= StringFormatFlags.NoClip;
        return f;
    }

    public static void Draw(Graphics g, string text, Font font, Color color, RectangleF r, StringAlignment h, StringAlignment v)
    {
        Draw(g, text, font, color, r, h, v, false, StringTrimming.EllipsisCharacter);
    }

    public static void Draw(Graphics g, string text, Font font, Color color, RectangleF r, StringAlignment h, StringAlignment v, bool wrap, StringTrimming trimming)
    {
        if (String.IsNullOrEmpty(text) || r.Width <= 1 || r.Height <= 1) return;
        using (StringFormat f = Format(h, v, wrap, trimming))
        using (SolidBrush b = new SolidBrush(color))
        {
            if (!wrap)
            {
                // Clip to the rectangle horizontally but let glyph descenders breathe vertically.
                f.FormatFlags &= ~StringFormatFlags.NoClip;
                RectangleF rr = new RectangleF(r.X, r.Y - 2, r.Width, r.Height + 4);
                g.DrawString(text, font, b, rr, f);
            }
            else g.DrawString(text, font, b, r, f);
        }
    }

    public static SizeF Measure(string text, Font font)
    {
        if (String.IsNullOrEmpty(text)) return new SizeF(0, font.GetHeight());
        lock (measureBitmap)
        {
            if (measureGraphics == null) { measureGraphics = Graphics.FromImage(measureBitmap); measureGraphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit; }
            using (StringFormat f = Format(StringAlignment.Near, StringAlignment.Near, false, StringTrimming.None))
                return measureGraphics.MeasureString(text, font, new PointF(0, 0), f);
        }
    }

    public static float MeasureHeight(string text, Font font, float width, int maxLines)
    {
        float line = LineHeight(font);
        if (String.IsNullOrEmpty(text)) return line;
        lock (measureBitmap)
        {
            if (measureGraphics == null) { measureGraphics = Graphics.FromImage(measureBitmap); measureGraphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit; }
            using (StringFormat f = Format(StringAlignment.Near, StringAlignment.Near, true, StringTrimming.None))
            {
                SizeF size = measureGraphics.MeasureString(text, font, new SizeF(Math.Max(1, width), 100000), f);
                float h = (float)Math.Ceiling(size.Height);
                if (maxLines > 0) h = Math.Min(h, line * maxLines);
                return Math.Max(line, h);
            }
        }
    }

    public static float LineHeight(Font font) { try { return (float)Math.Ceiling(font.GetHeight()); } catch { return (float)Math.Ceiling(font.Size * 1.3f); } }

    public static string FormatBytes(long bytes)
    {
        if (bytes < 1024) return bytes + " B";
        double value = bytes / 1024.0; string[] units = new string[] { "KB", "MB", "GB", "TB" }; int i = 0;
        while (value >= 1024 && i < units.Length - 1) { value /= 1024; i++; }
        return value.ToString(value >= 100 ? "0" : "0.0") + " " + units[i];
    }

    public static string Plural(int count, string one, string many) { return count + " " + (count == 1 ? one : many); }

    public static string MiddleTrim(string text, Font font, float width)
    {
        if (String.IsNullOrEmpty(text) || Measure(text, font).Width <= width) return text;
        int keep = text.Length;
        while (keep > 4)
        {
            keep--;
            int head = (keep + 1) / 2, tail = keep / 2;
            string candidate = text.Substring(0, head) + "…" + text.Substring(text.Length - tail);
            if (Measure(candidate, font).Width <= width) return candidate;
        }
        return text.Substring(0, Math.Min(text.Length, 2)) + "…";
    }

    public static void Later(int ms, Action action)
    {
        System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        timer.Interval = Math.Max(1, ms);
        timer.Tick += delegate { timer.Stop(); timer.Dispose(); try { action(); } catch { } };
        timer.Start();
    }

    public static Bitmap Snapshot(Control control)
    {
        if (control.Width <= 0 || control.Height <= 0) return null;
        try
        {
            Bitmap bitmap = new Bitmap(control.Width, control.Height, PixelFormat.Format32bppPArgb);
            control.DrawToBitmap(bitmap, new Rectangle(0, 0, control.Width, control.Height));
            return bitmap;
        }
        catch { return null; }
    }

    public static void DrawImageAlpha(Graphics g, Image image, Rectangle dest, float alpha)
    {
        if (image == null || alpha <= 0.003f) return;
        if (alpha >= 0.997f) { g.DrawImage(image, dest, 0, 0, image.Width, image.Height, GraphicsUnit.Pixel); return; }
        using (ImageAttributes attributes = new ImageAttributes())
        {
            ColorMatrix matrix = new ColorMatrix(); matrix.Matrix33 = alpha;
            attributes.SetColorMatrix(matrix, ColorMatrixFlag.Default, ColorAdjustType.Bitmap);
            g.DrawImage(image, dest, 0, 0, image.Width, image.Height, GraphicsUnit.Pixel, attributes);
        }
    }
}

// ---------------------------------------------------------------------------
// Animation: one shared ~60fps UI timer, cubic-bezier(0.2,0,0,1) tweens and springs.
// ---------------------------------------------------------------------------
internal sealed class Anim
{
    private static readonly List<Anim> active = new List<Anim>();
    private static readonly List<Func<bool>> tickers = new List<Func<bool>>();
    private static System.Windows.Forms.Timer timer;
    private static readonly Stopwatch clock = Stopwatch.StartNew();
    public static bool ReduceMotion;
    private const double Stiffness = 520.0;
    private static readonly double Damping = 2.0 * 0.84 * Math.Sqrt(Stiffness);

    public static double Now { get { return clock.Elapsed.TotalMilliseconds; } }

    public double Value;
    public Action Changed;
    public Action Finished;
    private double from, to, start, velocity, last;
    private int duration;
    private bool spring, running;

    public Anim(double value) { Value = from = to = value; }
    public double Target { get { return to; } }
    public bool Running { get { return running; } }

    public void To(double target, int ms)
    {
        if (running && !spring && target == to) return;
        if (!running && target == Value) { to = target; return; }
        from = Value; to = target; start = Now; duration = ms; spring = false; velocity = 0;
        if (ms <= 0) { Finish(); return; }
        Begin();
    }

    public void SpringTo(double target)
    {
        if (ReduceMotion) { To(target, 160); return; }
        if (!running && Math.Abs(target - Value) < 0.01) { to = target; return; }
        if (!spring) velocity = 0;
        to = target; spring = true;
        Begin();
    }

    public void Snap(double value)
    {
        Stop(); Value = from = to = value; velocity = 0;
        if (Changed != null) Changed();
    }

    public void Stop() { running = false; active.Remove(this); }

    private void Begin()
    {
        last = Now;
        if (!running) { running = true; active.Add(this); }
        EnsureTimer();
    }

    private void Finish()
    {
        Value = to; velocity = 0; Stop();
        if (Changed != null) Changed();
        if (Finished != null) Finished();
    }

    private bool Step(double now)
    {
        if (spring)
        {
            double dt = Math.Min(0.064, Math.Max(0, (now - last) / 1000.0)); last = now;
            int steps = Math.Max(1, (int)Math.Ceiling(dt / 0.004)); double h = dt / steps;
            for (int i = 0; i < steps; i++) { double a = -Stiffness * (Value - to) - Damping * velocity; velocity += a * h; Value += velocity * h; }
            if (Math.Abs(Value - to) < 0.2 && Math.Abs(velocity) < 4) return false;
            if (Changed != null) Changed();
            return true;
        }
        double t = duration <= 0 ? 1 : (now - start) / duration;
        if (t >= 1) return false;
        Value = from + (to - from) * Ease(t);
        if (Changed != null) Changed();
        return true;
    }

    // cubic-bezier(0.2, 0.0, 0.0, 1.0)
    public static double Ease(double p)
    {
        if (p <= 0) return 0; if (p >= 1) return 1;
        double lo = 0, hi = 1, t = p;
        for (int i = 0; i < 22; i++)
        {
            t = (lo + hi) / 2;
            double x = 3 * (1 - t) * (1 - t) * t * 0.2 + t * t * t;
            if (x < p) lo = t; else hi = t;
        }
        return 3 * (1 - t) * t * t + t * t * t;
    }

    public static void AddTicker(Func<bool> ticker)
    {
        if (!tickers.Contains(ticker)) tickers.Add(ticker);
        EnsureTimer();
    }

    private static void EnsureTimer()
    {
        if (timer == null)
        {
            timer = new System.Windows.Forms.Timer();
            timer.Interval = 15;
            timer.Tick += delegate { Tick(); };
        }
        if (!timer.Enabled) timer.Start();
    }

    private static void Tick()
    {
        double now = Now;
        Anim[] copy = active.ToArray();
        foreach (Anim a in copy)
        {
            if (!a.running) continue;
            bool more;
            try { more = a.Step(now); } catch { more = false; }
            if (!more && a.running) { try { a.Finish(); } catch { a.Stop(); } }
        }
        for (int i = tickers.Count - 1; i >= 0; i--)
        {
            bool keep;
            try { keep = tickers[i](); } catch { keep = false; }
            if (!keep && i < tickers.Count) tickers.RemoveAt(i);
        }
        if (active.Count == 0 && tickers.Count == 0 && timer != null) timer.Stop();
    }
}

// ---------------------------------------------------------------------------
// Vector glyphs on a 24-unit grid.
// ---------------------------------------------------------------------------
internal enum Glyph { None, Clipboard, Transfer, Settings, Phone, Laptop, Plus, Refresh, Close, Star, StarFilled, Check, File, Upload, Trash, Folder, Image, Download, Logo, Chevron }

internal static class Glyphs
{
    public static void Draw(Graphics g, Glyph glyph, RectangleF r, Color color, float rotation)
    {
        if (glyph == Glyph.None || r.Width <= 0) return;
        GraphicsState state = g.Save();
        try
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TranslateTransform(r.X + r.Width / 2f, r.Y + r.Height / 2f);
            if (rotation != 0) g.RotateTransform(rotation);
            g.ScaleTransform(r.Width / 24f, r.Height / 24f);
            g.TranslateTransform(-12f, -12f);
            using (Pen pen = new Pen(color, 1.8f))
            using (SolidBrush brush = new SolidBrush(color))
            {
                pen.StartCap = LineCap.Round; pen.EndCap = LineCap.Round; pen.LineJoin = LineJoin.Round;
                Paint(g, glyph, pen, brush);
            }
        }
        finally { g.Restore(state); }
    }

    private static void RoundRect(Graphics g, Pen pen, float x, float y, float w, float h, float radius)
    {
        using (GraphicsPath p = Ember.Round(new RectangleF(x, y, w, h), radius)) g.DrawPath(pen, p);
    }

    private static void Paint(Graphics g, Glyph glyph, Pen pen, SolidBrush brush)
    {
        switch (glyph)
        {
            case Glyph.Clipboard:
                RoundRect(g, pen, 5f, 4.5f, 14f, 16.5f, 2.6f);
                using (GraphicsPath clip = Ember.Round(new RectangleF(8.8f, 2.6f, 6.4f, 3.8f), 1.3f)) { g.DrawPath(pen, clip); }
                g.DrawLine(pen, 8.6f, 11.5f, 15.4f, 11.5f);
                g.DrawLine(pen, 8.6f, 15.5f, 13f, 15.5f);
                break;
            case Glyph.Transfer:
                g.DrawLine(pen, 4.5f, 8f, 19.5f, 8f); g.DrawLines(pen, new PointF[] { new PointF(15.5f, 4f), new PointF(19.5f, 8f), new PointF(15.5f, 12f) });
                g.DrawLine(pen, 19.5f, 16f, 4.5f, 16f); g.DrawLines(pen, new PointF[] { new PointF(8.5f, 12f), new PointF(4.5f, 16f), new PointF(8.5f, 20f) });
                break;
            case Glyph.Settings:
                g.DrawEllipse(pen, 9.2f, 9.2f, 5.6f, 5.6f);
                using (GraphicsPath gear = new GraphicsPath())
                {
                    int teeth = 8; float outer = 9.6f, inner = 7.4f;
                    List<PointF> pts = new List<PointF>();
                    for (int i = 0; i < teeth; i++)
                    {
                        double a0 = (i * 2 * Math.PI) / teeth; double half = Math.PI / teeth;
                        double[] angles = new double[] { a0 - half * 0.95, a0 - half * 0.45, a0 + half * 0.45, a0 + half * 0.95 };
                        float[] radii = new float[] { inner, outer, outer, inner };
                        for (int k = 0; k < 4; k++) pts.Add(new PointF(12f + (float)(Math.Cos(angles[k]) * radii[k]), 12f + (float)(Math.Sin(angles[k]) * radii[k])));
                    }
                    gear.AddPolygon(pts.ToArray());
                    g.DrawPath(pen, gear);
                }
                break;
            case Glyph.Phone:
                RoundRect(g, pen, 7f, 2.8f, 10f, 18.4f, 2.6f);
                g.DrawLine(pen, 10.8f, 17.8f, 13.2f, 17.8f);
                break;
            case Glyph.Laptop:
                RoundRect(g, pen, 4.5f, 5f, 15f, 10.5f, 1.6f);
                g.DrawLine(pen, 2.5f, 19f, 21.5f, 19f);
                break;
            case Glyph.Plus:
                g.DrawLine(pen, 12f, 5f, 12f, 19f); g.DrawLine(pen, 5f, 12f, 19f, 12f);
                break;
            case Glyph.Close:
                g.DrawLine(pen, 6.5f, 6.5f, 17.5f, 17.5f); g.DrawLine(pen, 17.5f, 6.5f, 6.5f, 17.5f);
                break;
            case Glyph.Refresh:
                g.DrawArc(pen, 5f, 5f, 14f, 14f, -60f, 300f);
                g.DrawLines(pen, new PointF[] { new PointF(15.2f, 4.2f), new PointF(15.8f, 7.6f), new PointF(19.2f, 7.1f) });
                break;
            case Glyph.Star:
            case Glyph.StarFilled:
                {
                    PointF[] star = new PointF[10];
                    for (int i = 0; i < 10; i++)
                    {
                        double angle = -Math.PI / 2 + i * Math.PI / 5; float radius = i % 2 == 0 ? 8.6f : 3.9f;
                        star[i] = new PointF(12f + (float)(Math.Cos(angle) * radius), 12.6f + (float)(Math.Sin(angle) * radius));
                    }
                    if (glyph == Glyph.StarFilled) g.FillPolygon(brush, star);
                    g.DrawPolygon(pen, star);
                }
                break;
            case Glyph.Check:
                g.DrawLines(pen, new PointF[] { new PointF(5.5f, 12.5f), new PointF(10f, 17f), new PointF(18.5f, 7.5f) });
                break;
            case Glyph.File:
                g.DrawLines(pen, new PointF[] { new PointF(14f, 3f), new PointF(6.5f, 3f), new PointF(6.5f, 21f), new PointF(17.5f, 21f), new PointF(17.5f, 6.5f), new PointF(14f, 3f), new PointF(14f, 6.5f), new PointF(17.5f, 6.5f) });
                break;
            case Glyph.Upload:
                g.DrawLine(pen, 12f, 15f, 12f, 4.5f); g.DrawLines(pen, new PointF[] { new PointF(7.5f, 9f), new PointF(12f, 4.5f), new PointF(16.5f, 9f) });
                g.DrawLines(pen, new PointF[] { new PointF(4.5f, 14.5f), new PointF(4.5f, 19.5f), new PointF(19.5f, 19.5f), new PointF(19.5f, 14.5f) });
                break;
            case Glyph.Download:
                g.DrawLine(pen, 12f, 4.5f, 12f, 15f); g.DrawLines(pen, new PointF[] { new PointF(7.5f, 10.5f), new PointF(12f, 15f), new PointF(16.5f, 10.5f) });
                g.DrawLine(pen, 5f, 19.5f, 19f, 19.5f);
                break;
            case Glyph.Trash:
                g.DrawLine(pen, 4.5f, 7f, 19.5f, 7f);
                g.DrawLines(pen, new PointF[] { new PointF(9.5f, 7f), new PointF(9.5f, 4.5f), new PointF(14.5f, 4.5f), new PointF(14.5f, 7f) });
                g.DrawLines(pen, new PointF[] { new PointF(6.5f, 7f), new PointF(7.5f, 20f), new PointF(16.5f, 20f), new PointF(17.5f, 7f) });
                break;
            case Glyph.Folder:
                g.DrawLines(pen, new PointF[] { new PointF(3.5f, 18.5f), new PointF(3.5f, 5.5f), new PointF(9.5f, 5.5f), new PointF(11.5f, 8f), new PointF(20.5f, 8f), new PointF(20.5f, 18.5f), new PointF(3.5f, 18.5f) });
                break;
            case Glyph.Image:
                RoundRect(g, pen, 3.5f, 4.5f, 17f, 15f, 2.4f);
                g.DrawEllipse(pen, 7f, 8f, 3f, 3f);
                g.DrawLines(pen, new PointF[] { new PointF(4f, 17.5f), new PointF(9.5f, 13f), new PointF(13f, 16f), new PointF(16f, 13.5f), new PointF(20f, 17f) });
                break;
            case Glyph.Chevron:
                g.DrawLines(pen, new PointF[] { new PointF(9.5f, 5.5f), new PointF(16f, 12f), new PointF(9.5f, 18.5f) });
                break;
            case Glyph.Logo:
                g.DrawLine(pen, 5.5f, 9f, 18.5f, 9f); g.DrawLines(pen, new PointF[] { new PointF(15f, 5.5f), new PointF(18.5f, 9f), new PointF(15f, 12.5f) });
                g.DrawLine(pen, 18.5f, 15f, 5.5f, 15f); g.DrawLines(pen, new PointF[] { new PointF(9f, 11.5f), new PointF(5.5f, 15f), new PointF(9f, 18.5f) });
                break;
        }
    }

    public static void Avatar(Graphics g, RectangleF r, bool phone, Color under, double alpha)
    {
        using (SolidBrush b = new SolidBrush(Ember.Ink(Ember.Fill07, under, alpha))) g.FillEllipse(b, r);
        float inset = r.Width * 0.24f;
        Draw(g, phone ? Glyph.Phone : Glyph.Laptop, new RectangleF(r.X + inset, r.Y + inset, r.Width - inset * 2, r.Height - inset * 2), Ember.Ink(Ember.TextSoft, under, alpha), 0);
    }

    public static bool LooksLikePhone(string type, string name)
    {
        string t = (type ?? "").ToLowerInvariant();
        if (t == "mobile" || t == "phone" || t == "tablet") return true;
        if (t == "desktop" || t == "laptop" || t == "computer") return false;
        string n = (name ?? "").ToLowerInvariant();
        foreach (string hint in new string[] { "phone", "pixel", "galaxy", "android", "samsung", "oneplus", "xiaomi", "redmi", "poco", "moto", "nokia", "oppo", "vivo", "realme", "huawei", "honor", "nothing", "ipad", "tablet" })
            if (n.Contains(hint)) return true;
        return false;
    }
}

// ---------------------------------------------------------------------------
// Base owner-drawn controls
// ---------------------------------------------------------------------------
internal class EmberControl : Control
{
    public EmberControl()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        SetStyle(ControlStyles.Selectable | ControlStyles.StandardClick | ControlStyles.StandardDoubleClick, false);
        DoubleBuffered = true;
        BackColor = Ember.Bg;
        ForeColor = Ember.Text;
        TabStop = false;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        Ember.Prepare(g);
        g.Clear(BackColor);
        Render(g);
    }

    protected virtual void Render(Graphics g) { }
}

internal class EmberPanel : Panel
{
    public EmberPanel()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        DoubleBuffered = true;
        BackColor = Ember.Bg;
    }
}

// Rounded Surface card (radius 20, 1px Line). Child controls should use BackColor = Ember.Surface.
internal sealed class Card : EmberPanel
{
    public Card() { BackColor = Ember.Bg; }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        Ember.Prepare(g);
        g.Clear(BackColor);
        RectangleF r = new RectangleF(0, 0, Width, Height);
        Ember.Fill(g, r, Ember.Sf(20), Ember.Surface);
        Ember.Stroke(g, r, Ember.Sf(20), Ember.Line, Math.Max(1f, (float)Math.Floor(Ember.Scale)));
        base.OnPaint(e);
    }
}

internal sealed class TextView : EmberControl
{
    private string text = "";
    private Font textFont;
    private Color textColor = Ember.Text;
    public StringAlignment Align = StringAlignment.Near;
    public StringAlignment VAlign = StringAlignment.Center;
    public bool Wrap;
    public StringTrimming Trimming = StringTrimming.EllipsisCharacter;

    public TextView(string value, Font font, Color color)
    {
        text = value ?? ""; textFont = font; textColor = color;
    }

    public override string Text
    {
        get { return text; }
        set { string v = value ?? ""; if (v == text) return; text = v; Invalidate(); }
    }

    public Font TextFont { get { return textFont; } set { textFont = value; Invalidate(); } }
    public Color TextColor { get { return textColor; } set { if (value == textColor) return; textColor = value; Invalidate(); } }

    public int PreferredHeightFor(int width, int maxLines)
    {
        if (!Wrap) return (int)Math.Ceiling(Ember.LineHeight(textFont)) + Ember.S(2);
        return (int)Math.Ceiling(Ember.MeasureHeight(text, textFont, width, maxLines)) + Ember.S(2);
    }

    protected override void Render(Graphics g)
    {
        Ember.Draw(g, text, textFont, Ember.Ink(textColor, BackColor, 1), new RectangleF(0, 0, Width, Height), Align, VAlign, Wrap, Trimming);
    }
}

internal enum PartKind { Primary, Secondary, Destructive, Ghost, Icon }

// A clickable region drawn inside a PartHost (buttons inside rows, cards, etc.).
internal sealed class Part
{
    public Rectangle Bounds;
    public string Text = "";
    public Glyph Glyph = Glyph.None;
    public PartKind Kind = PartKind.Secondary;
    public bool Enabled = true;
    public bool Visible = true;
    public bool Toggled;
    public Color ToggledColor = Ember.Accent;
    public Color IdleColor = Color.Empty;   // icon parts: glyph color at rest (default TextMuted)
    public Color HoverColor = Color.Empty;  // icon parts: glyph color on hover (default White)
    public string Tip;
    public Action Click;
    public float GlyphSize = 18f;
    public float FontSize = 13f;
    public readonly Anim Hover = new Anim(0);
    public readonly Anim Press = new Anim(0);
    public readonly Anim Spin = new Anim(0);

    public Part() { }
    public Part(PartKind kind, string text, Glyph glyph) { Kind = kind; Text = text ?? ""; Glyph = glyph; }

    public int PreferredWidth(int height)
    {
        if (Kind == PartKind.Icon || String.IsNullOrEmpty(Text)) return height;
        float w = Ember.Measure(Text, Ember.Font(FontSize, 600)).Width + Ember.Sf(Kind == PartKind.Ghost ? 24 : 36);
        if (Glyph != Glyph.None) w += Ember.Sf(GlyphSize + 6);
        return (int)Math.Ceiling(Math.Max(w, height * 1.6f));
    }
}

internal class PartHost : EmberControl
{
    public readonly List<Part> Parts = new List<Part>();
    public Action BackgroundClick;
    public readonly Anim HoverAnim = new Anim(0);
    public readonly Anim PressAnim = new Anim(0);
    private Part hot, pressed;
    private bool backgroundPressed;
    private static ToolTip tips;

    public PartHost()
    {
        HoverAnim.Changed = Invalidate;
        PressAnim.Changed = Invalidate;
    }

    public Part AddPart(Part part)
    {
        part.Hover.Changed = Invalidate;
        part.Press.Changed = Invalidate;
        part.Spin.Changed = Invalidate;
        Parts.Add(part);
        return part;
    }

    protected Part HitTest(Point p)
    {
        for (int i = Parts.Count - 1; i >= 0; i--)
        {
            Part part = Parts[i];
            if (part.Visible && part.Bounds.Contains(p)) return part;
        }
        return null;
    }

    private static ToolTip Tips
    {
        get
        {
            if (tips == null)
            {
                tips = new ToolTip(); tips.OwnerDraw = true; tips.InitialDelay = 450; tips.ReshowDelay = 120; tips.UseAnimation = false; tips.UseFading = false;
                tips.Popup += delegate(object s, PopupEventArgs e)
                {
                    string t = tips.GetToolTip(e.AssociatedControl);
                    SizeF size = Ember.Measure(t, Ember.Font(12, 500));
                    e.ToolTipSize = new Size((int)Math.Ceiling(size.Width) + Ember.S(20), (int)Math.Ceiling(size.Height) + Ember.S(12));
                };
                tips.Draw += delegate(object s, DrawToolTipEventArgs e)
                {
                    Graphics g = e.Graphics; Ember.Prepare(g);
                    g.Clear(Color.FromArgb(0x2C, 0x2C, 0x2C));
                    using (Pen pen = new Pen(Color.FromArgb(0x3A, 0x3A, 0x3A))) g.DrawRectangle(pen, 0, 0, e.Bounds.Width - 1, e.Bounds.Height - 1);
                    Ember.Draw(g, e.ToolTipText, Ember.Font(12, 500), Ember.TextSoft, new RectangleF(0, 0, e.Bounds.Width, e.Bounds.Height), StringAlignment.Center, StringAlignment.Center);
                };
            }
            return tips;
        }
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); HoverAnim.To(1, 120); }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        Part h = HitTest(e.Location);
        if (h != hot)
        {
            if (hot != null) hot.Hover.To(0, 120);
            hot = h;
            if (hot != null && hot.Enabled) hot.Hover.To(1, 120);
            string tip = hot != null ? hot.Tip : null;
            try { Tips.SetToolTip(this, tip ?? ""); } catch { }
        }
        bool clickable = (h != null && h.Enabled) || (h == null && BackgroundClick != null);
        Cursor wanted = clickable ? Cursors.Hand : Cursors.Default;
        if (Cursor != wanted) Cursor = wanted;
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        base.OnMouseLeave(e);
        if (hot != null) hot.Hover.To(0, 120);
        hot = null;
        HoverAnim.To(0, 120);
        if (pressed != null) { pressed.Press.To(0, 160); pressed = null; }
        if (backgroundPressed) { backgroundPressed = false; PressAnim.To(0, 160); }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        if (CanFocusOnClick && CanFocus) Focus();
        Part h = HitTest(e.Location);
        if (h != null)
        {
            if (h.Enabled) { pressed = h; h.Press.To(1, 100); }
        }
        else if (BackgroundClick != null) { backgroundPressed = true; PressAnim.To(1, 100); }
    }

    protected virtual bool CanFocusOnClick { get { return false; } }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e);
        if (e.Button != MouseButtons.Left) return;
        Part h = HitTest(e.Location);
        if (pressed != null)
        {
            Part p = pressed; pressed = null;
            p.Press.To(0, 180);
            if (h == p && p.Enabled && p.Visible) Activate(p);
        }
        else if (backgroundPressed)
        {
            backgroundPressed = false; PressAnim.To(0, 180);
            if (h == null && ClientRectangle.Contains(e.Location) && BackgroundClick != null) BackgroundClick();
        }
    }

    protected void Activate(Part p)
    {
        if (p.Glyph == Glyph.Refresh && !Anim.ReduceMotion) { p.Spin.Snap(0); p.Spin.To(1, 560); }
        if (p.Click != null) p.Click();
    }

    public void DrawPart(Graphics g, Part p, double alpha) { DrawPart(g, p, alpha, BackColor); }

    public void DrawPart(Graphics g, Part p, double alpha, Color under)
    {
        if (!p.Visible || p.Bounds.Width <= 0) return;
        under = Color.FromArgb(255, under);
        bool enabled = p.Enabled && Enabled;
        if (!enabled) alpha *= 0.4;
        float hover = enabled ? (float)p.Hover.Value : 0f, press = (float)p.Press.Value;
        RectangleF r = Ember.ScaleAround(p.Bounds, Anim.ReduceMotion ? 1f : 1f - 0.04f * press);
        Color bg, fg;
        switch (p.Kind)
        {
            case PartKind.Primary:
                bg = Ember.Mix(Ember.Mix(Ember.Accent, Ember.AccentHover, hover), Ember.AccentPressed, press); fg = Color.White; break;
            case PartKind.Destructive:
                bg = Ember.Mix(Ember.Mix(Ember.Negative, Ember.NegativeHover, hover), Color.FromArgb(0xE0, 0x55, 0x46), press); fg = Color.White; break;
            case PartKind.Ghost:
                bg = Ember.Mix(Color.FromArgb(0, 255, 255, 255), Ember.Fill07, Math.Max(hover, press)); fg = Ember.Mix(Ember.TextSoft, Color.White, hover); break;
            case PartKind.Icon:
                if (p.Toggled)
                {
                    bg = Ember.Mix(Ember.Mix(Ember.AccentSoft, Color.FromArgb(56, Ember.Accent), hover), Color.FromArgb(72, Ember.Accent), press);
                    fg = p.ToggledColor;
                }
                else
                {
                    bg = Ember.Mix(Ember.Mix(Color.FromArgb(0, 255, 255, 255), Ember.Fill07, hover), Ember.Fill12, press);
                    fg = Ember.Mix(p.IdleColor.IsEmpty ? Ember.TextMuted : p.IdleColor, p.HoverColor.IsEmpty ? Color.White : p.HoverColor, hover);
                }
                break;
            default:
                bg = Ember.Mix(Ember.Mix(Ember.Fill07, Ember.Fill12, hover), Ember.Fill20, press); fg = Color.White; break;
        }
        Ember.Fill(g, r, r.Height / 2f, Ember.Ink(bg, under, alpha));
        Color ink = Ember.Ink(fg, Ember.Over(bg, under), alpha);
        float gs = Ember.Sf(p.GlyphSize);
        float rotation = p.Glyph == Glyph.Refresh ? (float)(360.0 * p.Spin.Value) : 0f;
        if (String.IsNullOrEmpty(p.Text) || p.Kind == PartKind.Icon)
        {
            Glyphs.Draw(g, p.Glyph, new RectangleF(r.X + (r.Width - gs) / 2f, r.Y + (r.Height - gs) / 2f, gs, gs), ink, rotation);
            return;
        }
        Font font = Ember.Font(p.FontSize * (r.Height / Math.Max(1f, p.Bounds.Height)), 600);
        float textWidth = Ember.Measure(p.Text, font).Width;
        float total = textWidth + (p.Glyph != Glyph.None ? gs + Ember.Sf(6) : 0);
        float x = r.X + Math.Max(Ember.Sf(8), (r.Width - total) / 2f);
        if (p.Glyph != Glyph.None)
        {
            Glyphs.Draw(g, p.Glyph, new RectangleF(x, r.Y + (r.Height - gs) / 2f, gs, gs), ink, rotation);
            x += gs + Ember.Sf(6);
        }
        Ember.Draw(g, p.Text, font, ink, new RectangleF(x, r.Y, r.Right - x - Ember.Sf(6), r.Height), StringAlignment.Near, StringAlignment.Center);
    }

    protected override void Render(Graphics g)
    {
        foreach (Part p in Parts) DrawPart(g, p, 1.0);
    }
}

// Pill button: primary (accent), secondary (Fill07), destructive, ghost or icon-only.
internal sealed class PillButton : PartHost, IButtonControl
{
    private readonly Part part;
    private DialogResult dialogResult = DialogResult.None;

    public PillButton(string text, PartKind kind) : this(text, kind, Glyph.None) { }

    public PillButton(string text, PartKind kind, Glyph glyph)
    {
        SetStyle(ControlStyles.Selectable, true);
        TabStop = true;
        part = AddPart(new Part(kind, text, glyph));
        part.Click = delegate { PerformClick(); };
        Size = new Size(part.PreferredWidth(Ember.S(36)), Ember.S(36));
    }

    public Part Part { get { return part; } }
    public PartKind Kind { get { return part.Kind; } set { part.Kind = value; Invalidate(); } }
    public string Tip { get { return part.Tip; } set { part.Tip = value; } }
    public override string Text { get { return part == null ? "" : part.Text; } set { if (part == null) return; part.Text = value ?? ""; Invalidate(); } }
    public int PreferredWidth { get { return part.PreferredWidth(Height); } }
    protected override bool CanFocusOnClick { get { return false; } }

    public DialogResult DialogResult { get { return dialogResult; } set { dialogResult = value; } }
    public void NotifyDefault(bool value) { }
    public void PerformClick()
    {
        if (!Enabled || !part.Enabled) return;
        OnClick(EventArgs.Empty);
    }

    protected override void OnClick(EventArgs e)
    {
        base.OnClick(e);
        if (dialogResult != DialogResult.None)
        {
            Form form = FindForm();
            if (form != null) form.DialogResult = dialogResult;
        }
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); if (part != null) part.Bounds = ClientRectangle; }
    protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }
    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }

    protected override bool IsInputKey(Keys keyData) { return keyData == Keys.Space || base.IsInputKey(keyData); }
    protected override void OnKeyUp(KeyEventArgs e)
    {
        base.OnKeyUp(e);
        if (e.KeyCode == Keys.Space) { e.Handled = true; Activate(part); }
    }

    protected override void Render(Graphics g)
    {
        part.Bounds = ClientRectangle;
        DrawPart(g, part, 1.0);
        if (Focused && ShowFocusCues)
        {
            Ember.Stroke(g, new RectangleF(0, 0, Width, Height), Height / 2f, Color.FromArgb(200, Ember.Accent), Ember.Sf(1.5f));
        }
    }
}

internal sealed class ToggleSwitch : EmberControl
{
    private bool isChecked;
    private readonly Anim position = new Anim(0);
    private readonly Anim press = new Anim(0);
    private readonly Anim hover = new Anim(0);
    public event EventHandler CheckedChanged;

    public ToggleSwitch()
    {
        SetStyle(ControlStyles.Selectable, true);
        TabStop = true;
        Size = new Size(Ember.S(44), Ember.S(26));
        position.Changed = Invalidate; press.Changed = Invalidate; hover.Changed = Invalidate;
        Cursor = Cursors.Hand;
    }

    public bool Checked { get { return isChecked; } }

    public void SetChecked(bool value, bool animate)
    {
        isChecked = value;
        if (animate && IsHandleCreated && Visible) position.To(value ? 1 : 0, 160); else position.Snap(value ? 1 : 0);
    }

    private void Toggle()
    {
        if (!Enabled) return;
        SetChecked(!isChecked, true);
        if (CheckedChanged != null) CheckedChanged(this, EventArgs.Empty);
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hover.To(1, 120); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hover.To(0, 120); press.To(0, 160); }
    protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); if (e.Button == MouseButtons.Left) press.To(1, 100); }
    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e);
        if (e.Button != MouseButtons.Left) return;
        press.To(0, 180);
        if (ClientRectangle.Contains(e.Location)) Toggle();
    }
    protected override bool IsInputKey(Keys keyData) { return keyData == Keys.Space || base.IsInputKey(keyData); }
    protected override void OnKeyUp(KeyEventArgs e) { base.OnKeyUp(e); if (e.KeyCode == Keys.Space) Toggle(); }
    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
    protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }

    protected override void Render(Graphics g)
    {
        float t = (float)position.Value;
        double alpha = Enabled ? 1.0 : 0.45;
        RectangleF track = new RectangleF(0, 0, Width, Height);
        Color off = Ember.Mix(Ember.ToggleOff, Color.FromArgb(0x46, 0x46, 0x46), (float)hover.Value);
        Ember.Fill(g, track, Height / 2f, Ember.Ink(Ember.Mix(off, Ember.Accent, t), BackColor, alpha));
        float pad = Ember.Sf(3);
        float knob = Height - pad * 2;
        float stretch = Anim.ReduceMotion ? 0 : Ember.Sf(4) * (float)press.Value;
        float travel = Width - pad * 2 - knob - stretch;
        float x = pad + travel * t;
        RectangleF k = new RectangleF(x, pad, knob + stretch, knob);
        Ember.Fill(g, k, knob / 2f, Ember.Ink(Color.White, BackColor, alpha));
        if (Focused && ShowFocusCues) Ember.Stroke(g, new RectangleF(-0.5f, -0.5f, Width + 1, Height + 1), Height / 2f, Color.FromArgb(160, Ember.Accent), Ember.Sf(1.5f));
    }
}

internal sealed class StatusPill : PartHost
{
    private string text = "Starting…";
    private Color fromDot = Ember.Accent, toDot = Ember.Accent;
    private readonly Anim blend = new Anim(1);
    public Action Clicked;

    public StatusPill()
    {
        blend.Changed = Invalidate;
        Height = Ember.S(30);
        Width = PreferredWidth;
    }

    public int PreferredWidth { get { return (int)Math.Ceiling(Ember.Measure(text, Ember.Font(12, 500)).Width + Ember.Sf(40)); } }
    public override string Text { get { return text; } set { } }

    public void SetStatus(string value, Color dot, bool clickable)
    {
        BackgroundClick = clickable ? (Action)delegate { if (Clicked != null) Clicked(); } : null;
        if (value == text && dot == toDot) return;
        fromDot = Ember.Mix(fromDot, toDot, (float)blend.Value);
        toDot = dot; text = value ?? "";
        blend.Snap(0); blend.To(1, 160);
        int right = Right;
        Width = PreferredWidth;
        if (Parent != null) Left = right - Width;
        Invalidate();
    }

    protected override void Render(Graphics g)
    {
        float h = (float)HoverAnim.Value;
        RectangleF r = new RectangleF(0, 0, Width, Height);
        Color bg = BackgroundClick != null ? Ember.Mix(Ember.Fill06, Ember.Fill12, h) : Ember.Fill06;
        Ember.Fill(g, r, Height / 2f, Ember.Ink(bg, BackColor, 1));
        Ember.Stroke(g, r, Height / 2f, Ember.Line, 1f);
        Color dot = Ember.Mix(fromDot, toDot, (float)blend.Value);
        float d = Ember.Sf(8);
        using (SolidBrush b = new SolidBrush(dot)) g.FillEllipse(b, Ember.Sf(13), (Height - d) / 2f, d, d);
        Ember.Draw(g, text, Ember.Font(12, 500), Ember.TextSoft, new RectangleF(Ember.Sf(27), 0, Width - Ember.Sf(34), Height), StringAlignment.Near, StringAlignment.Center);
    }
}

// Row used inside RowList; animates insertion/removal (fade + height collapse).
internal class ListRow : PartHost
{
    public string Key = "";
    public int FullHeight = Ember.S(60);
    public bool Removing;
    public bool ShowDivider;
    public int DividerInset = Ember.S(64);
    public readonly Anim Appear = new Anim(1);

    public double Alpha { get { return Math.Max(0, Math.Min(1, Appear.Value)); } }

    protected override void Render(Graphics g)
    {
        if (ShowDivider)
        {
            using (SolidBrush b = new SolidBrush(Ember.Ink(Ember.Line, BackColor, Alpha)))
                g.FillRectangle(b, DividerInset, 0, Math.Max(0, Width - DividerInset - Ember.S(12)), Math.Max(1, (int)Math.Floor(Ember.Scale)));
        }
        RenderRow(g, Alpha);
    }

    protected virtual void RenderRow(Graphics g, double alpha) { foreach (Part p in Parts) DrawPart(g, p, alpha); }
}

internal sealed class RowList : EmberPanel
{
    private List<ListRow> display = new List<ListRow>();
    private readonly Dictionary<string, ListRow> byKey = new Dictionary<string, ListRow>();
    public int ContentHeight;
    public event Action HeightChanged;

    public RowList() { BackColor = Ember.Surface; }

    public int Count { get { int n = 0; foreach (ListRow r in display) if (!r.Removing) n++; return n; } }

    public List<ListRow> Rows { get { List<ListRow> list = new List<ListRow>(); foreach (ListRow r in display) if (!r.Removing) list.Add(r); return list; } }

    public ListRow Find(string key) { ListRow row; return byKey.TryGetValue(key, out row) && !row.Removing ? row : null; }

    public void Sync<T>(IList<T> items, Func<T, string> keyOf, Func<T, ListRow> create, Action<ListRow, T> update, bool animate)
    {
        if (Anim.ReduceMotion) animate = false;
        HashSet<string> keys = new HashSet<string>();
        List<ListRow> next = new List<ListRow>();
        foreach (T item in items)
        {
            string key = keyOf(item);
            if (key == null || keys.Contains(key)) continue;
            keys.Add(key);
            ListRow row;
            if (byKey.TryGetValue(key, out row))
            {
                if (row.Removing) { row.Removing = false; row.Appear.To(1, 220); }
                update(row, item);
            }
            else
            {
                row = create(item);
                row.Key = key;
                row.BackColor = Ember.Surface;
                ListRow captured = row;
                row.Appear.Changed = delegate { captured.Invalidate(); Relayout(); };
                row.Appear.Finished = delegate { if (captured.Removing && captured.Appear.Value <= 0.001) RemoveRow(captured); };
                update(row, item);
                byKey[key] = row;
                if (animate) row.Appear.Snap(0); else row.Appear.Snap(1);
                Controls.Add(row);
                if (animate) row.Appear.To(1, 220);
            }
            next.Add(row);
        }
        List<ListRow> immediate = new List<ListRow>();
        for (int i = 0; i < display.Count; i++)
        {
            ListRow old = display[i];
            if (keys.Contains(old.Key)) continue;
            if (!old.Removing)
            {
                old.Removing = true;
                if (animate) old.Appear.To(0, 200); else { immediate.Add(old); continue; }
            }
            next.Insert(Math.Min(i, next.Count), old);
        }
        display = next;
        foreach (ListRow r in immediate) DisposeRow(r);
        Relayout();
    }

    private void RemoveRow(ListRow row)
    {
        display.Remove(row);
        DisposeRow(row);
        Relayout();
    }

    private void DisposeRow(ListRow row)
    {
        ListRow mapped;
        if (byKey.TryGetValue(row.Key, out mapped) && mapped == row) byKey.Remove(row.Key);
        Controls.Remove(row);
        row.Appear.Stop();
        row.Dispose();
    }

    public void Relayout()
    {
        int y = 0; bool first = true;
        foreach (ListRow row in display)
        {
            int h = (int)Math.Round(row.FullHeight * Math.Max(0, Math.Min(1, row.Appear.Value)));
            row.ShowDivider = !first;
            if (row.Bounds != new Rectangle(0, y, Width, h)) row.SetBounds(0, y, Width, h);
            row.Visible = h > 0;
            if (h > 0) first = false;
            y += h;
        }
        if (y != ContentHeight)
        {
            ContentHeight = y;
            if (HeightChanged != null) HeightChanged();
        }
    }

    protected override void OnResize(EventArgs eventargs) { base.OnResize(eventargs); Relayout(); }
}

// Thin overlay scrollbar for ScrollPage.
internal sealed class ScrollThumb : EmberControl
{
    public ScrollPage Page;
    private readonly Anim hover = new Anim(0);
    private bool dragging; private int dragStartY; private double dragStartScroll;

    private readonly Anim shown = new Anim(0);
    private readonly System.Windows.Forms.Timer hideTimer = new System.Windows.Forms.Timer();

    public ScrollThumb()
    {
        hover.Changed = Invalidate; shown.Changed = Invalidate;
        hideTimer.Interval = 900;
        hideTimer.Tick += delegate { hideTimer.Stop(); if (!dragging && hover.Target < 0.5 && !IsDisposed) shown.To(0, 300); };
    }

    // Overlay scrollbar: appears while scrolling/hovered, fades out shortly after (one-shot timer).
    public void Flash()
    {
        if (shown.Target < 1) shown.To(1, 120);
        hideTimer.Stop(); hideTimer.Start();
    }

    protected override void Dispose(bool disposing) { if (disposing) hideTimer.Dispose(); base.Dispose(disposing); }

    private RectangleF ThumbRect()
    {
        if (Page == null || Page.ContentHeight <= Page.ClientSize.Height) return RectangleF.Empty;
        float view = Page.ClientSize.Height, total = Page.ContentHeight;
        float h = Math.Max(Ember.Sf(36), view * view / total);
        float y = (float)((view - h) * (Page.ScrollValue / Math.Max(1, total - view)));
        float w = Ember.Sf(4) + Ember.Sf(2) * (float)hover.Value;
        return new RectangleF(Width - w - Ember.Sf(3), y + Ember.Sf(2), w, h - Ember.Sf(4));
    }

    protected override void Render(Graphics g)
    {
        RectangleF r = ThumbRect();
        if (r.IsEmpty || shown.Value <= 0.01) return;
        Ember.Fill(g, r, r.Width / 2f, Ember.Ink(Ember.Mix(Ember.Fill20, Color.FromArgb(90, 255, 255, 255), (float)hover.Value), BackColor, shown.Value));
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hover.To(1, 120); if (Page != null && Page.ContentHeight > Page.ClientSize.Height) shown.To(1, 120); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); if (!dragging) { hover.To(0, 120); Flash(); } }
    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        RectangleF r = ThumbRect();
        if (r.IsEmpty || e.Button != MouseButtons.Left) return;
        if (e.Y >= r.Top && e.Y <= r.Bottom) { dragging = true; dragStartY = e.Y; dragStartScroll = Page.ScrollValue; Capture = true; }
        else Page.ScrollBy(e.Y < r.Top ? -Page.ClientSize.Height * 0.85 : Page.ClientSize.Height * 0.85);
    }
    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (!dragging || Page == null) return;
        float view = Page.ClientSize.Height, total = Page.ContentHeight;
        float h = Math.Max(Ember.Sf(36), view * view / total);
        double perPixel = (total - view) / Math.Max(1, view - h);
        Page.ScrollTo(dragStartScroll + (e.Y - dragStartY) * perPixel, false);
    }
    protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); dragging = false; Capture = false; if (!ClientRectangle.Contains(e.Location)) hover.To(0, 120); Flash(); }
}

// A page with smooth wheel scrolling and an overlay thumb. Arrange(width) lays out Content and returns its height.
internal sealed class ScrollPage : EmberPanel
{
    public readonly EmberPanel Content = new EmberPanel();
    private readonly ScrollThumb thumb = new ScrollThumb();
    private readonly Anim scroll = new Anim(0);
    public Func<int, int> Arrange;
    public int ContentHeight;
    private bool inLayout, layoutAgain;

    public ScrollPage()
    {
        Controls.Add(Content);
        thumb.Page = this;
        Controls.Add(thumb);
        thumb.BringToFront();
        scroll.Changed = ApplyScroll;
    }

    public double ScrollValue { get { return scroll.Value; } }

    public void RequestLayout()
    {
        if (inLayout) { layoutAgain = true; return; }
        inLayout = true;
        try
        {
            int guard = 0;
            do
            {
                layoutAgain = false;
                int width = ClientSize.Width;
                int height = Arrange == null ? ClientSize.Height : Arrange(width);
                ContentHeight = height;
                double max = Math.Max(0, ContentHeight - ClientSize.Height);
                if (scroll.Target > max || scroll.Value > max) scroll.Snap(Math.Min(scroll.Value, max));
                Rectangle bounds = new Rectangle(0, -(int)Math.Round(scroll.Value), width, Math.Max(height, ClientSize.Height));
                if (Content.Bounds != bounds) Content.Bounds = bounds;
                thumb.SetBounds(ClientSize.Width - Ember.S(12), 0, Ember.S(12), ClientSize.Height);
                thumb.Invalidate();
            } while (layoutAgain && ++guard < 4);
        }
        finally { inLayout = false; }
    }

    private void ApplyScroll()
    {
        int top = -(int)Math.Round(scroll.Value);
        if (Content.Top != top) Content.Top = top;
        thumb.Flash();
    }

    public void ScrollTo(double value, bool animate)
    {
        double max = Math.Max(0, ContentHeight - ClientSize.Height);
        value = Math.Max(0, Math.Min(max, value));
        if (animate && !Anim.ReduceMotion) scroll.To(value, 240); else scroll.Snap(value);
    }

    public void ScrollBy(double delta) { ScrollTo(scroll.Target + delta, true); }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        if (ContentHeight > ClientSize.Height)
        {
            ScrollBy(-e.Delta * Ember.Sf(0.9f));
            HandledMouseEventArgs handled = e as HandledMouseEventArgs;
            if (handled != null) handled.Handled = true;
        }
        base.OnMouseWheel(e);
    }

    protected override void OnResize(EventArgs eventargs) { base.OnResize(eventargs); RequestLayout(); }
}

// Opaque overlay that cross-fades a snapshot of the old page into the new one (with a short slide).
internal sealed class PageTransition : EmberControl
{
    private Bitmap oldShot, newShot;
    private int direction;
    private readonly Anim progress = new Anim(1);
    private Action done;

    public PageTransition() { progress.Changed = Invalidate; progress.Finished = Complete; Visible = false; }

    public bool Active { get { return Visible; } }

    public void Cover(Bitmap old)
    {
        DisposeShots();
        oldShot = old;
        progress.Snap(0);
        Visible = true;
        BringToFront();
        Update();
    }

    public void Play(Bitmap incoming, int dir, Action finished)
    {
        newShot = incoming; direction = dir; done = finished;
        progress.Snap(0);
        progress.To(1, 220);
    }

    public void Cancel() { progress.Stop(); Complete(); }

    private void Complete()
    {
        Visible = false;
        DisposeShots();
        Action d = done; done = null;
        if (d != null) d();
    }

    private void DisposeShots()
    {
        if (oldShot != null) { oldShot.Dispose(); oldShot = null; }
        if (newShot != null) { newShot.Dispose(); newShot = null; }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.Clear(BackColor);
        g.CompositingQuality = CompositingQuality.HighSpeed;
        g.InterpolationMode = InterpolationMode.NearestNeighbor;
        g.PixelOffsetMode = PixelOffsetMode.Half;
        double t = progress.Value;
        if (newShot != null)
        {
            int offset = Anim.ReduceMotion ? 0 : (int)Math.Round(direction * Ember.Sf(12) * (1 - t));
            Ember.DrawImageAlpha(g, newShot, new Rectangle(0, offset, newShot.Width, newShot.Height), (float)Math.Min(1, t * 1.25));
        }
        if (oldShot != null)
        {
            float a = newShot == null ? 1f : (float)(1 - Math.Min(1, t / 0.55));
            Ember.DrawImageAlpha(g, oldShot, new Rectangle(0, 0, oldShot.Width, oldShot.Height), a);
        }
    }

    protected override void Dispose(bool disposing) { if (disposing) DisposeShots(); base.Dispose(disposing); }
}

// Left navigation: wordmark, three icon+label items with one sliding accent pill, footer.
internal sealed class Sidebar : EmberControl
{
    private readonly string[] labels = new string[] { "Clipboard", "Transfer", "Settings" };
    private readonly Glyph[] glyphs = new Glyph[] { Glyph.Clipboard, Glyph.Transfer, Glyph.Settings };
    private readonly Anim[] hovers = new Anim[3];
    private readonly Anim[] presses = new Anim[3];
    private readonly Anim pill = new Anim(0);
    private int selected = 0, hot = -1, pressed = -1;
    public Action<int> Selected;
    public string Version = "";

    public Sidebar()
    {
        for (int i = 0; i < 3; i++) { hovers[i] = new Anim(0); hovers[i].Changed = Invalidate; presses[i] = new Anim(0); presses[i].Changed = Invalidate; }
        pill.Changed = Invalidate;
        pill.Snap(ItemRect(0).Y);
    }

    private Rectangle ItemRect(int i) { return new Rectangle(Ember.S(12), Ember.S(76) + i * Ember.S(46), Width - Ember.S(24), Ember.S(42)); }

    public void Select(int index, bool animate)
    {
        selected = index;
        if (animate && IsHandleCreated) pill.SpringTo(ItemRect(index).Y); else pill.Snap(ItemRect(index).Y);
        Invalidate();
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); if (!pill.Running) pill.Snap(ItemRect(selected).Y); }

    private int Hit(Point p) { for (int i = 0; i < 3; i++) if (ItemRect(i).Contains(p)) return i; return -1; }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        int h = Hit(e.Location);
        if (h == hot) return;
        if (hot >= 0) hovers[hot].To(0, 120);
        hot = h;
        if (hot >= 0) hovers[hot].To(1, 120);
        Cursor = hot >= 0 ? Cursors.Hand : Cursors.Default;
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        base.OnMouseLeave(e);
        if (hot >= 0) hovers[hot].To(0, 120);
        hot = -1;
        if (pressed >= 0) { presses[pressed].To(0, 160); pressed = -1; }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        pressed = Hit(e.Location);
        if (pressed >= 0) presses[pressed].To(1, 100);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e);
        if (pressed < 0) return;
        int p = pressed; pressed = -1;
        presses[p].To(0, 180);
        if (Hit(e.Location) == p && Selected != null) Selected(p);
    }

    protected override void Render(Graphics g)
    {
        // Wordmark
        float mark = Ember.Sf(28);
        RectangleF logo = new RectangleF(Ember.Sf(22), Ember.Sf(24), mark, mark);
        Ember.Fill(g, logo, Ember.Sf(9), Ember.Accent);
        Glyphs.Draw(g, Glyph.Logo, new RectangleF(logo.X + Ember.Sf(5), logo.Y + Ember.Sf(5), mark - Ember.Sf(10), mark - Ember.Sf(10)), Color.White, 0);
        Ember.Draw(g, "ClipMesh", Ember.Font(18, 600), Ember.Text, new RectangleF(logo.Right + Ember.Sf(11), logo.Y, Width - logo.Right - Ember.Sf(16), mark), StringAlignment.Near, StringAlignment.Center);

        // Hover backgrounds for unselected items
        float pitch = Ember.Sf(46);
        for (int i = 0; i < 3; i++)
        {
            Rectangle r = ItemRect(i);
            float hv = (float)hovers[i].Value;
            if (hv > 0.001f && i != selected) Ember.Fill(g, r, r.Height / 2f, Ember.Ink(Color.FromArgb((int)(13 * hv), 255, 255, 255), BackColor, 1));
        }
        // Sliding accent pill
        Rectangle first = ItemRect(0);
        RectangleF pillRect = new RectangleF(first.X, (float)pill.Value, first.Width, first.Height);
        int pressIndex = selected;
        float pressScale = Anim.ReduceMotion ? 1f : 1f - 0.03f * (float)presses[pressIndex].Value;
        Ember.Fill(g, Ember.ScaleAround(pillRect, pressScale), first.Height / 2f, Ember.Accent);
        // Items
        for (int i = 0; i < 3; i++)
        {
            Rectangle r = ItemRect(i);
            float overlap = 1f - Math.Min(1f, Math.Abs((float)pill.Value - r.Y) / pitch);
            Color baseColor = Ember.Ink(Ember.Mix(Ember.TextMuted, Ember.TextSoft, (float)hovers[i].Value), BackColor, 1);
            Color ink = Ember.Mix(baseColor, Color.White, overlap);
            float s = Anim.ReduceMotion || i == selected ? 1f : 1f - 0.03f * (float)presses[i].Value;
            RectangleF rr = Ember.ScaleAround(r, s);
            float gs = Ember.Sf(19);
            Glyphs.Draw(g, glyphs[i], new RectangleF(rr.X + Ember.Sf(16), rr.Y + (rr.Height - gs) / 2f, gs, gs), ink, 0);
            Ember.Draw(g, labels[i], Ember.Font(14, 500), ink, new RectangleF(rr.X + Ember.Sf(46), rr.Y, rr.Width - Ember.Sf(52), rr.Height), StringAlignment.Near, StringAlignment.Center);
        }
        // Footer: a single faint line.
        Font small = Ember.Font(11, 400);
        float lh = Ember.LineHeight(small);
        Ember.Draw(g, "ClipMesh " + Version, small, Ember.Ink(Ember.TextFaint, BackColor, 1), new RectangleF(Ember.Sf(24), Height - Ember.Sf(18) - lh, Width - Ember.Sf(40), lh), StringAlignment.Near, StringAlignment.Center);
        using (SolidBrush line = new SolidBrush(Ember.Ink(Ember.Line, BackColor, 1))) g.FillRectangle(line, Width - 1, 0, 1, Height);
    }
}

// ---------------------------------------------------------------------------
// Popups: per-pixel-alpha layered window, toast, modal backdrop, dialogs
// ---------------------------------------------------------------------------
internal class LayeredWindow : Form
{
    public LayeredWindow()
    {
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual;
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams cp = base.CreateParams;
            cp.ExStyle |= 0x80000 /*LAYERED*/ | 0x80 /*TOOLWINDOW*/ | 0x08000000 /*NOACTIVATE*/ | 0x20 /*TRANSPARENT*/;
            return cp;
        }
    }

    protected override bool ShowWithoutActivation { get { return true; } }

    public void Present(Bitmap bitmap, Point location, byte alpha)
    {
        if (bitmap == null || IsDisposed) return;
        if (!IsHandleCreated) CreateHandle();
        IntPtr screen = EmberNative.GetDC(IntPtr.Zero);
        IntPtr memory = EmberNative.CreateCompatibleDC(screen);
        IntPtr hbitmap = IntPtr.Zero, previous = IntPtr.Zero;
        try
        {
            hbitmap = bitmap.GetHbitmap(Color.FromArgb(0));
            previous = EmberNative.SelectObject(memory, hbitmap);
            EmberNative.SIZE size = new EmberNative.SIZE(bitmap.Width, bitmap.Height);
            EmberNative.POINT source = new EmberNative.POINT(0, 0);
            EmberNative.POINT target = new EmberNative.POINT(location.X, location.Y);
            EmberNative.BLENDFUNCTION blend = new EmberNative.BLENDFUNCTION();
            blend.BlendOp = 0; blend.BlendFlags = 0; blend.SourceConstantAlpha = alpha; blend.AlphaFormat = 1;
            EmberNative.UpdateLayeredWindow(Handle, screen, ref target, ref size, memory, ref source, 0, ref blend, 2);
        }
        catch { }
        finally
        {
            EmberNative.ReleaseDC(IntPtr.Zero, screen);
            if (hbitmap != IntPtr.Zero) { EmberNative.SelectObject(memory, previous); EmberNative.DeleteObject(hbitmap); }
            EmberNative.DeleteDC(memory);
        }
    }
}

internal enum ToastKind { Info, Success, Error }

// Bottom-center pill that fades/slides in, waits 2.4s and fades out.
internal sealed class Toast : LayeredWindow
{
    private static Toast current;
    private readonly Form host;
    private Bitmap bitmap;
    private readonly Anim appear = new Anim(0);
    private readonly System.Windows.Forms.Timer hold = new System.Windows.Forms.Timer();

    private Toast(Form owner)
    {
        host = owner;
        appear.Changed = Place;
        appear.Finished = delegate { if (appear.Value <= 0.001 && !IsDisposed) Hide(); };
        hold.Tick += delegate { hold.Stop(); appear.To(0, 180); };
        host.Move += delegate { if (Visible) Place(); };
        host.Resize += delegate { if (Visible) Place(); };
    }

    public static bool Show(Form owner, string text, ToastKind kind)
    {
        if (owner == null || owner.IsDisposed || !owner.Visible || owner.WindowState == FormWindowState.Minimized) return false;
        try
        {
            if (current == null || current.IsDisposed || current.host != owner) current = new Toast(owner);
            current.Display(text, kind);
            return true;
        }
        catch { return false; }
    }

    private void Display(string text, ToastKind kind)
    {
        Bitmap next = Render(text, kind);
        if (bitmap != null) bitmap.Dispose();
        bitmap = next;
        Rectangle area = TargetBounds(1);
        if (!Visible)
        {
            appear.Snap(0);
            Bounds = area;
            Show(host);
        }
        Place();
        appear.To(1, 220);
        hold.Stop();
        hold.Interval = 2400;
        hold.Start();
    }

    private Rectangle TargetBounds(double t)
    {
        Rectangle client = host.RectangleToScreen(host.ClientRectangle);
        int w = bitmap == null ? 10 : bitmap.Width, h = bitmap == null ? 10 : bitmap.Height;
        int x = client.Left + (client.Width - w) / 2;
        int lift = Anim.ReduceMotion ? 0 : (int)Math.Round(Ember.Sf(8) * (1 - t));
        int y = client.Bottom - Ember.S(28) - h + lift;
        return new Rectangle(x, y, w, h);
    }

    private void Place()
    {
        if (bitmap == null || IsDisposed) return;
        double t = Math.Max(0, Math.Min(1, appear.Value));
        Rectangle r = TargetBounds(t);
        Present(bitmap, r.Location, (byte)Math.Round(255 * t));
    }

    internal static Bitmap Render(string text, ToastKind kind)
    {
        Font font = Ember.Font(13, 500);
        string value = text ?? "";
        float maxText = Ember.Sf(520);
        float textWidth = Math.Min(maxText, Ember.Measure(value, font).Width + 1);
        int height = Ember.S(40);
        int icon = kind == ToastKind.Info ? 0 : Ember.S(16) + Ember.S(8);
        int width = (int)Math.Ceiling(textWidth) + Ember.S(36) + icon;
        Bitmap bmp = new Bitmap(width, height, PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(bmp))
        {
            g.Clear(Color.Transparent);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            RectangleF r = new RectangleF(0, 0, width, height);
            Color fill = Color.FromArgb(0x2A, 0x2A, 0x2A);
            Ember.Fill(g, r, height / 2f, fill);
            Ember.Stroke(g, r, height / 2f, Color.FromArgb(255, 0x3A, 0x3A, 0x3A), 1f);
            float x = Ember.Sf(18);
            if (kind == ToastKind.Success)
            {
                float d = Ember.Sf(16);
                using (SolidBrush b = new SolidBrush(Ember.Positive)) g.FillEllipse(b, x, (height - d) / 2f, d, d);
                Glyphs.Draw(g, Glyph.Check, new RectangleF(x + Ember.Sf(3), (height - d) / 2f + Ember.Sf(3), d - Ember.Sf(6), d - Ember.Sf(6)), Color.FromArgb(0x10, 0x30, 0x18), 0);
                x += d + Ember.Sf(8);
            }
            else if (kind == ToastKind.Error)
            {
                float d = Ember.Sf(8);
                using (SolidBrush b = new SolidBrush(Ember.Negative)) g.FillEllipse(b, x + Ember.Sf(4), (height - d) / 2f, d, d);
                x += Ember.Sf(16) + Ember.Sf(8);
            }
            Ember.Draw(g, value, font, Color.White, new RectangleF(x, 0, textWidth + 2, height), StringAlignment.Near, StringAlignment.Center);
        }
        return bmp;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { hold.Dispose(); if (bitmap != null) bitmap.Dispose(); }
        base.Dispose(disposing);
    }
}

// Dimmed backdrop over the owner window while a dialog is open.
internal sealed class Backdrop : Form
{
    private readonly Anim fade = new Anim(0);
    private bool closing;

    private Backdrop()
    {
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.Black;
        Opacity = 0;
        fade.Changed = delegate { if (!IsDisposed) { try { Opacity = Math.Max(0, Math.Min(0.55, fade.Value)); } catch { } } };
    }

    protected override CreateParams CreateParams
    {
        get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x80 | 0x08000000; return cp; }
    }

    protected override bool ShowWithoutActivation { get { return true; } }

    protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); EmberNative.DarkChrome(Handle, true); }

    public static Backdrop Over(Form owner)
    {
        if (owner == null || owner.IsDisposed || !owner.Visible || owner.WindowState == FormWindowState.Minimized) return null;
        try
        {
            Backdrop b = new Backdrop();
            b.Bounds = EmberNative.VisibleFrame(owner);
            b.Show(owner);
            b.fade.To(0.55, Anim.ReduceMotion ? 120 : 260);
            return b;
        }
        catch { return null; }
    }

    public void FadeOut()
    {
        if (closing || IsDisposed) return;
        closing = true;
        fade.Finished = delegate { try { Close(); Dispose(); } catch { } };
        fade.To(0, 180);
    }
}

// Borderless rounded dialog: Surface bg, radius 22, 1px Line, pill buttons, fade + slide entrance.
internal class EmberDialog : Form
{
    private readonly Anim enter = new Anim(0);
    private Backdrop backdrop;
    private Form ownerForm;
    private bool exiting, exitDone;
    private DialogResult pending = DialogResult.None;
    private int finalTop;
    protected readonly List<PillButton> Buttons = new List<PillButton>();

    public EmberDialog()
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        KeyPreview = true;
        BackColor = Ember.Surface;
        ForeColor = Ember.Text;
        Text = "ClipMesh";
        DoubleBuffered = true;
        Opacity = 0;
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        enter.Changed = delegate
        {
            if (IsDisposed) return;
            try { Opacity = Math.Max(0, Math.Min(1, enter.Value)); } catch { }
            if (!Anim.ReduceMotion) Top = finalTop + (int)Math.Round(Ember.Sf(10) * (1 - enter.Value));
        };
    }

    // title, message (may be empty), optional body control and right-aligned buttons.
    public void Build(string title, string message, Control body, int width)
    {
        int pad = Ember.S(24), inner = width - pad * 2, y = pad;
        if (!String.IsNullOrEmpty(title))
        {
            TextView t = new TextView(title, Ember.Font(18, 600), Ember.Text); t.BackColor = Ember.Surface; t.Wrap = true; t.VAlign = StringAlignment.Near;
            int h = t.PreferredHeightFor(inner, 3); t.SetBounds(pad, y, inner, h); Controls.Add(t); y += h + Ember.S(8);
        }
        if (!String.IsNullOrEmpty(message))
        {
            TextView m = new TextView(message, Ember.Font(14, 400), Ember.TextMuted); m.BackColor = Ember.Surface; m.Wrap = true; m.VAlign = StringAlignment.Near; m.Trimming = StringTrimming.EllipsisWord;
            int h = m.PreferredHeightFor(inner, 14); m.SetBounds(pad, y, inner, h); Controls.Add(m); y += h + Ember.S(4);
        }
        if (body != null)
        {
            y += Ember.S(12);
            body.SetBounds(pad, y, inner, body.Height); Controls.Add(body); y += body.Height;
        }
        y += Buttons.Count > 0 ? Ember.S(22) : Ember.S(10);
        int x = width - pad;
        for (int i = Buttons.Count - 1; i >= 0; i--)
        {
            PillButton b = Buttons[i]; b.BackColor = Ember.Surface;
            int w = Math.Max(Ember.S(92), b.PreferredWidth);
            x -= w; b.SetBounds(x, y, w, Ember.S(38)); x -= Ember.S(10);
            Controls.Add(b);
        }
        if (Buttons.Count > 0) y += Ember.S(38);
        y += pad;
        ClientSize = new Size(width, y);
    }

    public PillButton AddButton(string text, PartKind kind, DialogResult result)
    {
        PillButton b = new PillButton(text, kind);
        b.DialogResult = result;
        b.Height = Ember.S(38);
        Buttons.Add(b);
        return b;
    }

    private static Form Resolve(IWin32Window owner)
    {
        if (owner == null) return null;
        Form f = owner as Form;
        if (f != null) return f;
        try { return Control.FromHandle(owner.Handle) as Form; } catch { return null; }
    }

    private void PrepareOwner(IWin32Window owner)
    {
        ownerForm = Resolve(owner);
        bool ownerShown = ownerForm != null && !ownerForm.IsDisposed && ownerForm.Visible && ownerForm.WindowState != FormWindowState.Minimized;
        Rectangle area;
        if (ownerShown) area = EmberNative.VisibleFrame(ownerForm);
        else
        {
            area = Screen.FromPoint(Cursor.Position).WorkingArea;
            ShowInTaskbar = true;
            TopMost = true;
        }
        Left = area.Left + (area.Width - Width) / 2;
        finalTop = area.Top + Math.Max(0, (area.Height - Height) / 2 - Ember.S(12));
        Top = Anim.ReduceMotion ? finalTop : finalTop + Ember.S(10);
        if (ownerShown && !(ownerForm is EmberDialog)) backdrop = Backdrop.Over(ownerForm);
        if (!ownerShown) ownerForm = null;
    }

    public DialogResult ShowModal(IWin32Window owner)
    {
        PrepareOwner(owner);
        return ownerForm != null ? ShowDialog(ownerForm) : ShowDialog();
    }

    public void ShowModeless(IWin32Window owner)
    {
        PrepareOwner(owner);
        if (ownerForm != null) Show(ownerForm); else Show();
    }

    protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); EmberNative.DarkChrome(Handle, false); }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        enter.To(1, Anim.ReduceMotion ? 140 : 260);
        try { Activate(); } catch { }
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        if (Width <= 0 || Height <= 0) return;
        using (GraphicsPath p = Ember.Round(new RectangleF(0, 0, Width, Height), Ember.Sf(22)))
        {
            Region old = Region;
            Region = new Region(p);
            if (old != null) old.Dispose();
        }
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        Ember.Prepare(g);
        g.Clear(Ember.Surface);
        Ember.Stroke(g, new RectangleF(0, 0, Width, Height), Ember.Sf(22), Color.FromArgb(0x38, 0x38, 0x38), 1f);
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        try { EmberNative.ReleaseCapture(); EmberNative.SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero); } catch { }
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        if (e.KeyCode == Keys.Escape && CancelButton == null && !e.Handled) { e.Handled = true; Close(); }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        if (e.Cancel) return;
        bool animated = !exitDone && (e.CloseReason == CloseReason.UserClosing || e.CloseReason == CloseReason.None) && IsHandleCreated && Visible;
        if (animated)
        {
            e.Cancel = true;
            if (exiting) return;
            exiting = true;
            pending = DialogResult;
            if (backdrop != null) { backdrop.FadeOut(); backdrop = null; }
            enter.Finished = delegate
            {
                exitDone = true;
                if (IsDisposed) return;
                if (Modal) DialogResult = pending == DialogResult.None ? DialogResult.Cancel : pending;
                else Close();
            };
            enter.To(0, Anim.ReduceMotion ? 100 : 180);
            return;
        }
        if (backdrop != null) { backdrop.FadeOut(); backdrop = null; }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        base.OnFormClosed(e);
        enter.Stop();
        if (backdrop != null) { try { backdrop.Close(); } catch { } backdrop = null; }
        if (ownerForm != null && !ownerForm.IsDisposed) { try { ownerForm.Activate(); } catch { } }
    }
}

// Rounded single-line text input (radius 14) used by Prompt.
internal sealed class EmberInput : EmberPanel
{
    public readonly TextBox Box = new TextBox();
    private readonly Anim focus = new Anim(0);
    private readonly Color fill;

    public EmberInput(bool monospace)
    {
        fill = Ember.Over(Ember.Fill06, Ember.Surface);
        BackColor = Ember.Surface;
        Height = Ember.S(46);
        Box.BorderStyle = BorderStyle.None;
        Box.BackColor = fill;
        Box.ForeColor = Color.White;
        Box.Font = monospace ? Ember.Mono(15) : Ember.Font(14, 400);
        Controls.Add(Box);
        focus.Changed = Invalidate;
        Box.GotFocus += delegate { focus.To(1, 160); };
        Box.LostFocus += delegate { focus.To(0, 160); };
        Cursor = Cursors.IBeam;
    }

    public string Value { get { return Box.Text; } set { Box.Text = value ?? ""; } }

    protected override void OnResize(EventArgs eventargs)
    {
        base.OnResize(eventargs);
        int h = Box.PreferredHeight;
        Box.SetBounds(Ember.S(14), Math.Max(0, (Height - h) / 2), Math.Max(10, Width - Ember.S(28)), h);
    }

    protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); Box.Focus(); }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics; Ember.Prepare(g); g.Clear(BackColor);
        RectangleF r = new RectangleF(0, 0, Width, Height);
        Ember.Fill(g, r, Ember.Sf(14), fill);
        Color border = Ember.Mix(Ember.Over(Ember.Line, fill), Ember.Accent, (float)focus.Value);
        Ember.Stroke(g, r, Ember.Sf(14), border, Ember.Sf(1.25f));
    }
}

// Big monospaced verification code with a gently pulsing caption.
internal sealed class CodeBox : EmberControl
{
    private readonly string code;
    private readonly Func<bool> ticker;

    public CodeBox(string value)
    {
        code = value ?? "";
        BackColor = Ember.Surface;
        Height = Ember.S(150);
        ticker = delegate { if (IsDisposed || !Visible) return false; Invalidate(); return true; };
    }

    protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); if (Visible && !Anim.ReduceMotion) Anim.AddTicker(ticker); }

    protected override void Render(Graphics g)
    {
        RectangleF box = new RectangleF(0, 0, Width, Ember.Sf(104));
        Ember.Fill(g, box, Ember.Sf(18), Ember.Over(Ember.Fill05, Ember.Surface));
        Font font = Ember.Mono(46);
        float gap = Ember.Sf(8);
        float[] widths = new float[code.Length]; float total = 0;
        for (int i = 0; i < code.Length; i++) { widths[i] = Ember.Measure(code[i].ToString(), font).Width; total += widths[i] + (i > 0 ? gap : 0); }
        if (code.Length == 6) total += gap * 2;
        float x = (Width - total) / 2f;
        for (int i = 0; i < code.Length; i++)
        {
            if (i > 0) x += gap;
            if (i == 3 && code.Length == 6) x += gap * 2;
            Ember.Draw(g, code[i].ToString(), font, Color.White, new RectangleF(x, box.Y, widths[i] + 2, box.Height), StringAlignment.Near, StringAlignment.Center);
            x += widths[i];
        }
        double pulse = Anim.ReduceMotion ? 1 : 0.6 + 0.4 * (0.5 + 0.5 * Math.Sin(Anim.Now / 520.0));
        Ember.Draw(g, "Waiting for confirmation…", Ember.Font(13, 400), Ember.Ink(Ember.TextMuted, BackColor, pulse), new RectangleF(0, box.Bottom + Ember.Sf(14), Width, Ember.Sf(24)), StringAlignment.Center, StringAlignment.Center);
    }
}

internal static class ClipMeshDialogC
{
    public static bool Show(IWin32Window owner, string title, string message, bool confirm)
    {
        return Show(owner, title, message, confirm ? "Continue" : "Done", confirm ? "Cancel" : null, false);
    }

    public static bool Show(IWin32Window owner, string title, string message, string acceptText, string cancelText, bool destructive)
    {
        Ember.Init();
        using (EmberDialog dialog = new EmberDialog())
        {
            PillButton cancel = cancelText == null ? null : dialog.AddButton(cancelText, PartKind.Secondary, DialogResult.Cancel);
            PillButton accept = dialog.AddButton(acceptText, cancelText == null ? PartKind.Secondary : (destructive ? PartKind.Destructive : PartKind.Primary), DialogResult.OK);
            dialog.Build(title, message, null, Ember.S(440));
            dialog.AcceptButton = accept;
            dialog.CancelButton = cancel ?? accept;
            return dialog.ShowModal(owner) == DialogResult.OK;
        }
    }

    public static string Prompt(IWin32Window owner, string title, string hint, string current, string acceptText, bool monospace)
    {
        Ember.Init();
        using (EmberDialog dialog = new EmberDialog())
        {
            EmberInput input = new EmberInput(monospace);
            input.Value = current;
            PillButton cancel = dialog.AddButton("Cancel", PartKind.Secondary, DialogResult.Cancel);
            PillButton accept = dialog.AddButton(acceptText, PartKind.Primary, DialogResult.OK);
            dialog.Build(title, hint, input, Ember.S(440));
            dialog.AcceptButton = accept;
            dialog.CancelButton = cancel;
            dialog.Shown += delegate { input.Box.Focus(); input.Box.SelectAll(); };
            return dialog.ShowModal(owner) == DialogResult.OK ? input.Value : null;
        }
    }
}

internal sealed class DarkMenuColors : ProfessionalColorTable
{
    private static readonly Color Menu = Color.FromArgb(0x26, 0x26, 0x26);
    private static readonly Color Hot = Color.FromArgb(0x33, 0x33, 0x33);
    private static readonly Color Edge = Color.FromArgb(0x3A, 0x3A, 0x3A);
    public override Color ToolStripDropDownBackground { get { return Menu; } }
    public override Color ImageMarginGradientBegin { get { return Menu; } }
    public override Color ImageMarginGradientMiddle { get { return Menu; } }
    public override Color ImageMarginGradientEnd { get { return Menu; } }
    public override Color MenuBorder { get { return Edge; } }
    public override Color MenuItemBorder { get { return Hot; } }
    public override Color MenuItemSelected { get { return Hot; } }
    public override Color MenuItemSelectedGradientBegin { get { return Hot; } }
    public override Color MenuItemSelectedGradientEnd { get { return Hot; } }
    public override Color MenuItemPressedGradientBegin { get { return Hot; } }
    public override Color MenuItemPressedGradientEnd { get { return Hot; } }
    public override Color SeparatorDark { get { return Edge; } }
    public override Color SeparatorLight { get { return Menu; } }
}

internal sealed class DarkMenuRenderer : ToolStripProfessionalRenderer
{
    public DarkMenuRenderer() : base(new DarkMenuColors()) { RoundedEdges = false; }

    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
    {
        e.TextColor = e.Item.Enabled ? Ember.TextSoft : Color.FromArgb(0x77, 0x77, 0x77);
        base.OnRenderItemText(e);
    }

    protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e)
    {
        Rectangle r = e.Item.ContentRectangle;
        using (SolidBrush b = new SolidBrush(Color.FromArgb(0x3A, 0x3A, 0x3A)))
            e.Graphics.FillRectangle(b, r.Left + Ember.S(8), r.Top + r.Height / 2, r.Width - Ember.S(16), 1);
    }
}

// ---------------------------------------------------------------------------
// Images (never lock files: decode from a shared FileStream and copy)
// ---------------------------------------------------------------------------
internal static class ImageLoader
{
    private static readonly string[] ImageExtensions = new string[] { ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff" };

    public static bool IsImagePath(string path)
    {
        try { return Array.IndexOf(ImageExtensions, (Path.GetExtension(path) ?? "").ToLowerInvariant()) >= 0; } catch { return false; }
    }

    public static Bitmap LoadFile(string path, int maxEdge)
    {
        using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (Image image = Image.FromStream(stream, false, false))
        {
            RotateFlipType rotation = Orientation(image);
            Bitmap result = Fit(image, maxEdge);
            if (rotation != RotateFlipType.RotateNoneFlipNone) result.RotateFlip(rotation);
            return result;
        }
    }

    private static RotateFlipType Orientation(Image image)
    {
        try
        {
            if (Array.IndexOf(image.PropertyIdList, 0x0112) < 0) return RotateFlipType.RotateNoneFlipNone;
            PropertyItem item = image.GetPropertyItem(0x0112);
            int value = item.Value != null && item.Value.Length > 0 ? item.Value[0] : 1;
            switch (value)
            {
                case 2: return RotateFlipType.RotateNoneFlipX;
                case 3: return RotateFlipType.Rotate180FlipNone;
                case 4: return RotateFlipType.Rotate180FlipX;
                case 5: return RotateFlipType.Rotate90FlipX;
                case 6: return RotateFlipType.Rotate90FlipNone;
                case 7: return RotateFlipType.Rotate270FlipX;
                case 8: return RotateFlipType.Rotate270FlipNone;
            }
        }
        catch { }
        return RotateFlipType.RotateNoneFlipNone;
    }

    public static Bitmap Fit(Image image, int maxEdge)
    {
        int w = image.Width, h = image.Height;
        double scale = Math.Min(1.0, maxEdge / (double)Math.Max(1, Math.Max(w, h)));
        int tw = Math.Max(1, (int)Math.Round(w * scale)), th = Math.Max(1, (int)Math.Round(h * scale));
        Bitmap result = new Bitmap(tw, th, PixelFormat.Format32bppPArgb);
        using (Graphics g = Graphics.FromImage(result))
        {
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.CompositingQuality = CompositingQuality.HighQuality;
            g.Clear(Color.Transparent);
            using (ImageAttributes wrap = new ImageAttributes())
            {
                wrap.SetWrapMode(WrapMode.TileFlipXY);
                g.DrawImage(image, new Rectangle(0, 0, tw, th), 0, 0, w, h, GraphicsUnit.Pixel, wrap);
            }
        }
        return result;
    }

    public static void LoadAsync(Control owner, string path, int maxEdge, Action<Bitmap> done)
    {
        SynchronizationContext ui = SynchronizationContext.Current;
        ThreadPool.QueueUserWorkItem(delegate
        {
            Bitmap bitmap = null;
            try { bitmap = LoadFile(path, maxEdge); } catch { bitmap = null; }
            SendOrPostCallback deliver = delegate
            {
                if (owner.IsDisposed) { if (bitmap != null) bitmap.Dispose(); return; }
                done(bitmap);
            };
            try
            {
                if (ui != null) ui.Post(deliver, null);
                else if (!owner.IsDisposed && owner.IsHandleCreated) owner.BeginInvoke(deliver, new object[] { null });
                else if (bitmap != null) bitmap.Dispose();
            }
            catch { if (bitmap != null) bitmap.Dispose(); }
        });
    }

    // Draws image to fill dest (center crop) clipped to a rounded rect.
    public static void DrawCover(Graphics g, Image image, RectangleF dest, float radius, double alpha)
    {
        if (image == null) return;
        float scale = Math.Max(dest.Width / image.Width, dest.Height / image.Height);
        float sw = dest.Width / scale, sh = dest.Height / scale;
        RectangleF src = new RectangleF((image.Width - sw) / 2f, (image.Height - sh) / 2f, sw, sh);
        DrawClipped(g, image, dest, src, radius, alpha);
    }

    public static void DrawClipped(Graphics g, Image image, RectangleF dest, RectangleF src, float radius, double alpha)
    {
        GraphicsState state = g.Save();
        try
        {
            using (GraphicsPath path = Ember.Round(dest, radius))
            {
                g.SetClip(path, CombineMode.Intersect);
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                using (ImageAttributes attributes = new ImageAttributes())
                {
                    attributes.SetWrapMode(WrapMode.TileFlipXY);
                    if (alpha < 0.997)
                    {
                        ColorMatrix matrix = new ColorMatrix(); matrix.Matrix33 = (float)Math.Max(0, alpha);
                        attributes.SetColorMatrix(matrix, ColorMatrixFlag.Default, ColorAdjustType.Bitmap);
                    }
                    g.DrawImage(image, Rectangle.Round(dest), src.X, src.Y, src.Width, src.Height, GraphicsUnit.Pixel, attributes);
                }
            }
        }
        finally { g.Restore(state); }
    }
}

// ---------------------------------------------------------------------------
// Clipboard preview model (never exposes raw format names)
// ---------------------------------------------------------------------------
internal enum ClipKind { Empty, Image, Files, Text, Unknown }

internal sealed class ClipContent : IDisposable
{
    public ClipKind Kind = ClipKind.Empty;
    public Bitmap Image;           // capped full image for the modal
    public string ImagePath;       // set when the image comes from a copied file (loaded async)
    public string ImageFormat = "";
    public bool ImagePending;
    public readonly List<string> Files = new List<string>();
    public string Text = "";
    public uint Sequence;

    public string Badge
    {
        get { return Kind == ClipKind.Image ? "Image" : Kind == ClipKind.Files ? "Files" : Kind == ClipKind.Text ? "Text" : ""; }
    }

    public string ImageCaption
    {
        get
        {
            string size = Image == null ? "" : Image.Width + "×" + Image.Height;
            if (!String.IsNullOrEmpty(ImagePath))
            {
                string name = Path.GetFileName(ImagePath);
                if (Files.Count > 1) name += " +" + (Files.Count - 1) + " more";
                return size.Length > 0 && Files.Count <= 1 ? name + " · " + size : name;
            }
            return size.Length == 0 ? ImageFormat : ImageFormat + " · " + size;
        }
    }

    public void Dispose()
    {
        if (Image != null) { Image.Dispose(); Image = null; }
    }
}

internal static class ClipboardReader
{
    public const int MaxImageEdge = 4096;

    public static ClipContent Read()
    {
        ClipContent content = new ClipContent();
        try { content.Sequence = EmberNative.GetClipboardSequenceNumber(); } catch { }
        IDataObject data = null;
        for (int attempt = 0; attempt < 4 && data == null; attempt++)
        {
            try { data = Clipboard.GetDataObject(); }
            catch (ExternalException) { Thread.Sleep(40); }
            catch { break; }
        }
        if (data == null) return content;
        string[] formats = new string[0];
        try { formats = data.GetFormats(false) ?? new string[0]; } catch { }

        // 1. Files first (Explorer copies may also carry an icon bitmap).
        try
        {
            if (data.GetDataPresent(DataFormats.FileDrop))
            {
                string[] files = data.GetData(DataFormats.FileDrop) as string[];
                if (files != null && files.Length > 0)
                {
                    content.Files.AddRange(files);
                    bool allImages = true;
                    foreach (string f in files) if (!ImageLoader.IsImagePath(f)) { allImages = false; break; }
                    if (allImages && File.Exists(files[0]))
                    {
                        content.Kind = ClipKind.Image;
                        content.ImagePath = files[0];
                        content.ImagePending = true;
                        content.ImageFormat = (Path.GetExtension(files[0]) ?? "").TrimStart('.').ToUpperInvariant();
                    }
                    else content.Kind = ClipKind.Files;
                    return content;
                }
            }
        }
        catch { }

        // 2. Bitmap data: prefer the PNG stream (keeps transparency), then CF_DIB/CF_BITMAP.
        try
        {
            if (data.GetDataPresent("PNG"))
            {
                Stream stream = data.GetData("PNG") as Stream;
                if (stream != null)
                {
                    using (MemoryStream copy = new MemoryStream())
                    {
                        stream.CopyTo(copy);
                        copy.Position = 0;
                        using (Image png = Image.FromStream(copy)) content.Image = ImageLoader.Fit(png, MaxImageEdge);
                    }
                    content.ImageFormat = "PNG";
                }
            }
        }
        catch { content.Image = null; }
        if (content.Image == null)
        {
            try
            {
                if (Clipboard.ContainsImage())
                {
                    using (Image image = Clipboard.GetImage())
                    {
                        if (image != null) { content.Image = ImageLoader.Fit(image, MaxImageEdge); content.ImageFormat = "Image"; }
                    }
                }
            }
            catch { content.Image = null; }
        }
        if (content.Image != null) { content.Kind = ClipKind.Image; return content; }

        // 3. Text, then HTML / RTF converted to plain text.
        string text = null;
        try { if (Clipboard.ContainsText(TextDataFormat.UnicodeText)) text = Clipboard.GetText(TextDataFormat.UnicodeText); } catch { }
        try { if (String.IsNullOrEmpty(text) && Clipboard.ContainsText(TextDataFormat.Text)) text = Clipboard.GetText(TextDataFormat.Text); } catch { }
        try { if (String.IsNullOrEmpty(text) && Clipboard.ContainsText(TextDataFormat.Html)) text = HtmlToText(Clipboard.GetText(TextDataFormat.Html)); } catch { }
        try
        {
            if (String.IsNullOrEmpty(text) && Clipboard.ContainsText(TextDataFormat.Rtf))
                using (RichTextBox rich = new RichTextBox()) { rich.Rtf = Clipboard.GetText(TextDataFormat.Rtf); text = rich.Text; }
        }
        catch { }
        if (!String.IsNullOrEmpty(text) && text.Trim().Length > 0)
        {
            content.Kind = ClipKind.Text;
            content.Text = text.Length > 200000 ? text.Substring(0, 200000) : text;
            return content;
        }
        content.Kind = formats.Length == 0 ? ClipKind.Empty : ClipKind.Unknown;
        return content;
    }

    public static string HtmlToText(string html)
    {
        if (String.IsNullOrEmpty(html)) return "";
        string body = html;
        int start = body.IndexOf("<!--StartFragment-->", StringComparison.OrdinalIgnoreCase);
        int end = body.IndexOf("<!--EndFragment-->", StringComparison.OrdinalIgnoreCase);
        if (start >= 0 && end > start) body = body.Substring(start + 20, end - start - 20);
        else
        {
            int tag = body.IndexOf('<');
            if (tag > 0) body = body.Substring(tag);
        }
        body = System.Text.RegularExpressions.Regex.Replace(body, @"<(script|style)[^>]*>.*?</\1>", "", System.Text.RegularExpressions.RegexOptions.Singleline | System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        body = System.Text.RegularExpressions.Regex.Replace(body, @"<\s*(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        body = System.Text.RegularExpressions.Regex.Replace(body, @"<[^>]+>", "");
        body = System.Net.WebUtility.HtmlDecode(body);
        body = System.Text.RegularExpressions.Regex.Replace(body, @"[ \t ]+", " ");
        body = System.Text.RegularExpressions.Regex.Replace(body, @"\n\s*\n\s*\n+", "\n\n");
        return body.Trim();
    }

    public static string FirstLines(string text, int lines, int maxChars)
    {
        string normalized = (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n').Replace('\t', ' ');
        string[] parts = normalized.Split('\n');
        StringBuilder sb = new StringBuilder();
        int count = 0;
        foreach (string part in parts)
        {
            if (count >= lines) break;
            if (count > 0) sb.Append('\n');
            sb.Append(part.Length > maxChars ? part.Substring(0, maxChars) : part);
            count++;
        }
        return sb.ToString().TrimEnd();
    }
}

// Live "Current clipboard" card: one compact row [64px tile | title, caption, 2-line preview | chevron].
internal sealed class ClipboardCard : PartHost
{
    private ClipContent content = new ClipContent();
    private string preview = "";
    private Bitmap thumb;
    private readonly Anim height = new Anim(0);
    private readonly Anim fade = new Anim(1);
    public Action HeightChanged;

    private const float Pad = 14f, Tile = 64f;

    public ClipboardCard()
    {
        height.Changed = delegate { if (HeightChanged != null) HeightChanged(); };
        fade.Changed = Invalidate;
        height.Snap(Ember.S(Pad * 2 + Tile));
    }

    public int CurrentHeight { get { return (int)Math.Round(height.Value); } }
    public ClipContent Content { get { return content; } }

    public void SetContent(ClipContent next, bool animate)
    {
        ClipContent old = content;
        content = next ?? new ClipContent();
        if (old != null && old != content) old.Dispose();
        preview = content.Kind == ClipKind.Text ? ClipboardReader.FirstLines(content.Text, 2, 300).Replace('\n', ' ') : "";
        RebuildThumb();
        Retarget(animate);
        if (animate && !Anim.ReduceMotion) { fade.Snap(0.3); fade.To(1, 200); } else fade.Snap(1);
        Invalidate();
    }

    public void ImageLoaded(ClipContent target, Bitmap image)
    {
        if (target != content) { if (image != null) image.Dispose(); return; }
        content.ImagePending = false;
        if (image == null) content.Kind = content.Files.Count > 0 ? ClipKind.Files : ClipKind.Unknown;
        else content.Image = image;
        RebuildThumb();
        Retarget(true);
        Invalidate();
    }

    private void RebuildThumb()
    {
        if (thumb != null) { thumb.Dispose(); thumb = null; }
        if (content.Image != null) { try { thumb = ImageLoader.Fit(content.Image, Ember.S(160)); } catch { thumb = null; } }
    }

    public void Retarget(bool animate)
    {
        int target = DesiredHeight(Width);
        if (animate && IsHandleCreated && Visible && !Anim.ReduceMotion) height.To(target, 200); else height.Snap(target);
    }

    private string TitleText
    {
        get
        {
            switch (content.Kind)
            {
                case ClipKind.Image: return !String.IsNullOrEmpty(content.ImagePath) ? Path.GetFileName(content.ImagePath) : "Image";
                case ClipKind.Files: return content.Files.Count == 1 ? Path.GetFileName(content.Files[0].TrimEnd('\\')) : Ember.Plural(content.Files.Count, "file", "files");
                case ClipKind.Text: return "Text";
                case ClipKind.Unknown: return "No preview available";
                default: return "Clipboard is empty";
            }
        }
    }

    private string CaptionText
    {
        get
        {
            switch (content.Kind)
            {
                case ClipKind.Image:
                    {
                        string fmt = content.ImageFormat;
                        string size = content.Image == null ? "" : content.Image.Width + "×" + content.Image.Height;
                        string c = size.Length == 0 ? fmt : (fmt.Length == 0 ? size : fmt + " · " + size);
                        if (content.Files.Count > 1) c += " · +" + (content.Files.Count - 1) + " more";
                        return c;
                    }
                case ClipKind.Files:
                    {
                        if (content.Files.Count == 1) return Directory.Exists(content.Files[0]) ? "Folder" : (Path.GetDirectoryName(content.Files[0]) ?? "");
                        List<string> names = new List<string>();
                        for (int i = 0; i < content.Files.Count && i < 4; i++) names.Add(Path.GetFileName(content.Files[i].TrimEnd('\\')));
                        return String.Join(", ", names.ToArray());
                    }
                case ClipKind.Text: return content.Text.Length.ToString("N0") + (content.Text.Length == 1 ? " character" : " characters");
                case ClipKind.Unknown: return "This content can't be shown here";
                default: return "Copy something to see it here";
            }
        }
    }

    private float TextLeft { get { return Ember.Sf(Pad + Tile + 14); } }
    private float TextRight(int width) { return width - Ember.Sf(Pad + 16 + 8); }

    public int DesiredHeight(int width)
    {
        float body = Ember.Sf(20) + Ember.Sf(17);
        if (content.Kind == ClipKind.Text && preview.Length > 0)
            body += Ember.Sf(4) + Ember.MeasureHeight(preview, Ember.Font(13, 400), Math.Max(10, TextRight(width) - TextLeft), 2);
        return (int)Math.Ceiling(Math.Max(Ember.Sf(Tile), body) + Ember.Sf(Pad * 2));
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        if (!height.Running && Width > 0) { int target = DesiredHeight(Width); if (target != CurrentHeight) height.Snap(target); }
    }

    protected override void Render(Graphics g)
    {
        float hv = (float)HoverAnim.Value;
        RectangleF card = new RectangleF(0, 0, Width, Height);
        Color surface = Ember.Mix(Ember.Surface, Ember.Over(Ember.Fill05, Ember.Surface), hv * 0.7f);
        float pr = 1f - 0.006f * (float)PressAnim.Value;
        Ember.Fill(g, Ember.ScaleAround(card, Anim.ReduceMotion ? 1f : pr), Ember.Sf(20), surface);
        Ember.Stroke(g, card, Ember.Sf(20), Ember.Mix(Ember.Line, Ember.Fill12, hv), 1f);
        double a = fade.Value;
        float pad = Ember.Sf(Pad), tile = Ember.Sf(Tile);
        RectangleF t = new RectangleF(pad, (Height - tile) / 2f, tile, tile);
        if (content.Kind == ClipKind.Image && thumb != null) ImageLoader.DrawCover(g, thumb, t, Ember.Sf(12), a);
        else
        {
            Ember.Fill(g, t, Ember.Sf(12), Ember.Ink(content.Kind == ClipKind.Empty ? Ember.Fill05 : Ember.Fill07, surface, a));
            Color ink = Ember.Ink(content.Kind == ClipKind.Empty ? Ember.TextFaint : Ember.TextSoft, surface, a);
            if (content.Kind == ClipKind.Text)
                Ember.Draw(g, "T", Ember.Font(24, 600), ink, t, StringAlignment.Center, StringAlignment.Center);
            else
            {
                float gs = Ember.Sf(26);
                Glyph glyph = content.Kind == ClipKind.Files ? (content.Files.Count == 1 && Directory.Exists(content.Files[0]) ? Glyph.Folder : Glyph.File)
                    : content.Kind == ClipKind.Image ? Glyph.Image : Glyph.Clipboard;
                Glyphs.Draw(g, glyph, new RectangleF(t.X + (tile - gs) / 2, t.Y + (tile - gs) / 2, gs, gs), ink, 0);
            }
        }
        float x = TextLeft, right = TextRight(Width), w = Math.Max(10, right - x);
        float bodyH = Ember.Sf(20) + Ember.Sf(17);
        float previewH = 0;
        if (content.Kind == ClipKind.Text && preview.Length > 0) { previewH = Ember.MeasureHeight(preview, Ember.Font(13, 400), w, 2); bodyH += Ember.Sf(4) + previewH; }
        float y = (Height - bodyH) / 2f;
        bool empty = content.Kind == ClipKind.Empty || content.Kind == ClipKind.Unknown;
        Ember.Draw(g, TitleText, Ember.Font(15, 500), Ember.Ink(empty ? Ember.TextMuted : Color.White, surface, a), new RectangleF(x, y, w, Ember.Sf(20)), StringAlignment.Near, StringAlignment.Center);
        Ember.Draw(g, CaptionText, Ember.Font(12, 400), Ember.Ink(Ember.TextMuted, surface, a), new RectangleF(x, y + Ember.Sf(20), w, Ember.Sf(17)), StringAlignment.Near, StringAlignment.Center, false, content.Kind == ClipKind.Files && content.Files.Count == 1 ? StringTrimming.EllipsisPath : StringTrimming.EllipsisCharacter);
        if (previewH > 0)
            Ember.Draw(g, preview, Ember.Font(13, 400), Ember.Ink(Ember.TextSoft, surface, a), new RectangleF(x, y + Ember.Sf(41), w, previewH + 1), StringAlignment.Near, StringAlignment.Near, true, StringTrimming.EllipsisWord);
        float cs = Ember.Sf(16);
        Glyphs.Draw(g, Glyph.Chevron, new RectangleF(Width - pad - cs, (Height - cs) / 2f, cs, cs), Ember.Ink(Ember.Mix(Ember.TextFaint, Ember.TextSoft, hv), surface, 1), 0);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { if (thumb != null) thumb.Dispose(); if (content != null) content.Dispose(); }
        base.Dispose(disposing);
    }
}

// Fit-to-view image used in the clipboard modal.
internal sealed class ImageView : EmberControl
{
    private readonly Image image;
    public ImageView(Image value) { image = value; BackColor = Ember.Surface; }
    protected override void Render(Graphics g)
    {
        RectangleF area = new RectangleF(0, 0, Width, Height);
        Ember.Fill(g, area, Ember.Sf(16), Ember.Over(Ember.Fill05, Ember.Surface));
        if (image == null) return;
        double scale = Math.Min(1.0 * Width / image.Width, 1.0 * Height / image.Height);
        scale = Math.Min(scale, Math.Max(1.0, Ember.Scale));
        float w = (float)(image.Width * scale), h = (float)(image.Height * scale);
        RectangleF dest = new RectangleF((Width - w) / 2f, (Height - h) / 2f, w, h);
        ImageLoader.DrawClipped(g, image, dest, new RectangleF(0, 0, image.Width, image.Height), Ember.Sf(12), 1);
    }
}

// Scrollable file list (with thumbnails for image files) used in the clipboard modal.
internal sealed class FileListView : EmberControl
{
    private readonly List<string> files;
    private readonly Dictionary<string, Bitmap> thumbs = new Dictionary<string, Bitmap>();
    private readonly Anim scroll = new Anim(0);
    private int RowHeight { get { return Ember.S(52); } }

    public FileListView(List<string> paths)
    {
        files = paths;
        BackColor = Ember.Surface;
        scroll.Changed = Invalidate;
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        int count = 0;
        foreach (string path in files)
        {
            if (count >= 60) break;
            if (!ImageLoader.IsImagePath(path)) continue;
            count++;
            string p = path;
            ImageLoader.LoadAsync(this, p, Ember.S(96), delegate(Bitmap b) { if (b == null) return; thumbs[p] = b; Invalidate(); });
        }
    }

    public int ContentHeight { get { return files.Count * RowHeight; } }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        double max = Math.Max(0, ContentHeight - Height);
        if (max > 0)
        {
            double target = Math.Max(0, Math.Min(max, scroll.Target - e.Delta * Ember.Sf(0.8f)));
            if (Anim.ReduceMotion) scroll.Snap(target); else scroll.To(target, 200);
            HandledMouseEventArgs handled = e as HandledMouseEventArgs; if (handled != null) handled.Handled = true;
        }
        base.OnMouseWheel(e);
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); Focus(); }

    protected override void Render(Graphics g)
    {
        int rh = RowHeight;
        int first = Math.Max(0, (int)(scroll.Value / rh));
        for (int i = first; i < files.Count; i++)
        {
            float y = (float)(i * rh - scroll.Value);
            if (y > Height) break;
            string path = files[i];
            float s = Ember.Sf(40);
            RectangleF icon = new RectangleF(0, y + (rh - s) / 2f, s, s);
            Bitmap thumb;
            if (thumbs.TryGetValue(path, out thumb)) ImageLoader.DrawCover(g, thumb, icon, Ember.Sf(10), 1);
            else
            {
                Ember.Fill(g, icon, Ember.Sf(10), Ember.Over(Ember.Fill06, BackColor));
                float gs = Ember.Sf(20);
                Glyphs.Draw(g, Directory.Exists(path) ? Glyph.Folder : Glyph.File, new RectangleF(icon.X + (s - gs) / 2, icon.Y + (s - gs) / 2, gs, gs), Ember.Ink(Ember.TextMuted, BackColor, 1), 0);
            }
            float x = s + Ember.Sf(14);
            Ember.Draw(g, Path.GetFileName(path.TrimEnd('\\')), Ember.Font(14, 500), Ember.TextSoft, new RectangleF(x, y + Ember.Sf(7), Width - x, Ember.Sf(20)), StringAlignment.Near, StringAlignment.Center);
            Ember.Draw(g, Path.GetDirectoryName(path) ?? "", Ember.Font(12, 400), Ember.Ink(Ember.TextMuted, BackColor, 1), new RectangleF(x, y + Ember.Sf(27), Width - x, Ember.Sf(18)), StringAlignment.Near, StringAlignment.Center, false, StringTrimming.EllipsisPath);
        }
        double max = Math.Max(0, ContentHeight - Height);
        if (max > 0)
        {
            float th = Math.Max(Ember.Sf(30), (float)Height * Height / ContentHeight);
            float ty = (float)((Height - th) * scroll.Value / max);
            Ember.Fill(g, new RectangleF(Width - Ember.Sf(4), ty, Ember.Sf(4), th), Ember.Sf(2), Ember.Ink(Ember.Fill20, BackColor, 1));
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) foreach (Bitmap b in thumbs.Values) b.Dispose();
        base.Dispose(disposing);
    }
}

internal sealed class RoundedHost : EmberPanel
{
    private readonly Color fill;
    public RoundedHost(Control child, Color background)
    {
        fill = background; BackColor = Ember.Surface;
        Padding = new Padding(Ember.S(14), Ember.S(12), Ember.S(6), Ember.S(12));
        child.Dock = DockStyle.Fill;
        Controls.Add(child);
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics; Ember.Prepare(g); g.Clear(BackColor);
        Ember.Fill(g, new RectangleF(0, 0, Width, Height), Ember.Sf(14), fill);
        Ember.Stroke(g, new RectangleF(0, 0, Width, Height), Ember.Sf(14), Ember.Over(Ember.Line, fill), 1f);
    }
}

internal static class ClipboardViewer
{
    public static void Show(Form owner, ClipContent content)
    {
        Rectangle frame = owner != null && owner.Visible ? EmberNative.VisibleFrame(owner) : Screen.PrimaryScreen.WorkingArea;
        int width = Math.Max(Ember.S(440), Math.Min(Ember.S(860), (int)(frame.Width * 0.84)));
        int inner = width - Ember.S(48);
        int maxBody = Math.Max(Ember.S(200), Math.Min(Ember.S(520), (int)(frame.Height * 0.84) - Ember.S(200)));
        using (EmberDialog dialog = new EmberDialog())
        {
            Control body = null;
            string message;
            switch (content == null ? ClipKind.Empty : content.Kind)
            {
                case ClipKind.Image:
                    if (content.Image != null)
                    {
                        double scale = Math.Min(1.0, Math.Min(1.0 * inner / content.Image.Width, 1.0 * maxBody / content.Image.Height));
                        ImageView view = new ImageView(content.Image);
                        view.Height = Math.Max(Ember.S(160), (int)Math.Ceiling(content.Image.Height * Math.Max(scale, 0.01)));
                        body = view;
                    }
                    message = content.ImageCaption;
                    break;
                case ClipKind.Files:
                    {
                        FileListView list = new FileListView(new List<string>(content.Files));
                        list.Height = Math.Min(maxBody, Math.Max(Ember.S(52), list.ContentHeight));
                        body = list;
                        message = Ember.Plural(content.Files.Count, "file", "files");
                    }
                    break;
                case ClipKind.Text:
                    {
                        TextBox box = new TextBox();
                        box.Multiline = true; box.ReadOnly = true; box.WordWrap = true; box.ScrollBars = ScrollBars.Vertical;
                        box.BorderStyle = BorderStyle.None;
                        Color fill = Ember.Over(Ember.Fill05, Ember.Surface);
                        box.BackColor = fill; box.ForeColor = Ember.TextSoft; box.Font = Ember.Font(14, 400);
                        box.Text = content.Text.Replace("\r\n", "\n").Replace("\n", "\r\n");
                        box.HandleCreated += delegate { EmberNative.DarkScrollbars(box.Handle); box.Select(0, 0); };
                        RoundedHost host = new RoundedHost(box, fill);
                        host.Height = Math.Min(maxBody, Math.Max(Ember.S(120), (int)Ember.MeasureHeight(content.Text.Length > 20000 ? content.Text.Substring(0, 20000) : content.Text, box.Font, inner - Ember.S(30), 0) + Ember.S(30)));
                        body = host;
                        message = content.Text.Length.ToString("N0") + (content.Text.Length == 1 ? " character" : " characters");
                    }
                    break;
                case ClipKind.Unknown:
                    message = "This clipboard content can't be previewed.";
                    break;
                default:
                    message = "Clipboard is empty.";
                    break;
            }
            PillButton done = dialog.AddButton("Done", PartKind.Secondary, DialogResult.OK);
            dialog.Build("Current clipboard", message, body, width);
            dialog.AcceptButton = done;
            dialog.CancelButton = done;
            dialog.ShowModal(owner);
        }
    }
}

// ---------------------------------------------------------------------------
// Transfer page: selection card, incoming banner
// ---------------------------------------------------------------------------
internal sealed class SelectionCard : PartHost
{
    private sealed class Tile
    {
        public string Path;
        public long Size;
        public bool Removing;
        public Bitmap Thumb;
        public readonly Anim Appear = new Anim(0);
        public readonly Anim X = new Anim(0);
        public readonly Anim Hover = new Anim(0);
        public Part Remove;
    }

    private readonly List<Tile> tiles = new List<Tile>();
    private readonly Part clear;
    private readonly Anim mode = new Anim(0);
    private readonly Anim drag = new Anim(0);
    private readonly Anim scrollX = new Anim(0);
    private Tile hoverTile;
    private string header = "";
    public Action Choose;
    public Action<string> RemoveFile;
    public Action ClearAll;

    private int TileW { get { return Ember.S(76); } }
    private int TileH { get { return Ember.S(76 + 22); } }
    private int Pitch { get { return Ember.S(86); } }
    private readonly Anim height = new Anim(0);
    public Action HeightChanged;
    public int CurrentHeight { get { return (int)Math.Round(height.Value); } }
    private int EmptyHeight { get { return Ember.S(120); } }
    private int FilesHeight { get { return Ember.S(14 + 28 + 10) + TileH + Ember.S(12); } }

    private void SetMode(int target, bool animate)
    {
        bool anim = animate && !Anim.ReduceMotion;
        mode.To(target, anim ? 200 : 0);
        int h = target == 1 ? FilesHeight : EmptyHeight;
        if (anim) height.To(h, 220); else height.Snap(h);
    }

    public SelectionCard()
    {
        height.Snap(EmptyHeight);
        height.Changed = delegate { if (HeightChanged != null) HeightChanged(); };
        mode.Changed = Invalidate; drag.Changed = Invalidate; scrollX.Changed = Invalidate;
        clear = AddPart(new Part(PartKind.Ghost, "Clear", Glyph.None));
        clear.Click = delegate { if (ClearAll != null) ClearAll(); };
        BackgroundClick = delegate { if (Choose != null) Choose(); };
    }

    public bool DragHot { set { drag.To(value ? 1 : 0, 160); } }

    public void Sync(IList<string> files, bool animate)
    {
        if (Anim.ReduceMotion) animate = false;
        HashSet<string> wanted = new HashSet<string>(files, StringComparer.OrdinalIgnoreCase);
        foreach (Tile t in tiles.ToArray())
        {
            if (wanted.Contains(t.Path) && !t.Removing) continue;
            if (wanted.Contains(t.Path) && t.Removing) { t.Removing = false; t.Appear.To(1, 200); continue; }
            if (t.Removing) continue;
            t.Removing = true;
            if (animate) t.Appear.To(0, 180); else DropTile(t);
        }
        foreach (string path in files)
        {
            if (FindTile(path) != null) continue;
            Tile t = new Tile(); t.Path = path;
            try { t.Size = new FileInfo(path).Length; } catch { t.Size = 0; }
            Tile captured = t;
            t.Appear.Changed = Invalidate; t.X.Changed = Invalidate; t.Hover.Changed = Invalidate;
            t.Appear.Finished = delegate { if (captured.Removing && captured.Appear.Value <= 0.001) { DropTile(captured); Reflow(true); } };
            t.Remove = AddPart(new Part(PartKind.Icon, "", Glyph.Close));
            t.Remove.GlyphSize = 12; t.Remove.Visible = false; t.Remove.Tip = "Remove";
            t.Remove.Click = delegate { if (RemoveFile != null) RemoveFile(captured.Path); };
            tiles.Add(t);
            if (ImageLoader.IsImagePath(path))
                ImageLoader.LoadAsync(this, path, Ember.S(176), delegate(Bitmap b) { if (captured.Removing || IsDisposed) { if (b != null) b.Dispose(); return; } captured.Thumb = b; Invalidate(); });
            t.X.Snap(SlotX(tiles.Count - 1 - CountRemovingBefore(tiles.Count - 1)));
            if (animate) t.Appear.To(1, 220); else t.Appear.Snap(1);
        }
        int live = 0; long total = 0;
        foreach (Tile t in tiles) if (!t.Removing) { live++; total += t.Size; }
        header = live == 0 ? "" : Ember.Plural(live, "file", "files") + " · " + Ember.FormatBytes(total);
        if (live > 0) SetMode(1, animate);
        else if (!AnyRemoving()) SetMode(0, animate);
        BackgroundClick = live == 0 ? (Action)delegate { if (Choose != null) Choose(); } : null;
        Reflow(animate);
        Invalidate();
    }

    private bool AnyRemoving() { foreach (Tile t in tiles) if (t.Removing) return true; return false; }
    private int CountRemovingBefore(int index) { int n = 0; for (int i = 0; i < index && i < tiles.Count; i++) if (tiles[i].Removing) n++; return n; }
    private Tile FindTile(string path) { foreach (Tile t in tiles) if (String.Equals(t.Path, path, StringComparison.OrdinalIgnoreCase) && !t.Removing) return t; return null; }
    private int SlotX(int index) { return Ember.S(14) + index * Pitch; }

    private void DropTile(Tile t)
    {
        tiles.Remove(t);
        Parts.Remove(t.Remove);
        t.Appear.Stop(); t.X.Stop(); t.Hover.Stop();
        if (t.Thumb != null) { t.Thumb.Dispose(); t.Thumb = null; }
        if (hoverTile == t) hoverTile = null;
        bool live = false; foreach (Tile x in tiles) if (!x.Removing) live = true;
        if (!live && !AnyRemoving()) SetMode(0, true);
        Invalidate();
    }

    private void Reflow(bool animate)
    {
        int slot = 0;
        foreach (Tile t in tiles)
        {
            if (t.Removing) continue;
            int x = SlotX(slot++);
            if (animate) t.X.To(x, 220); else t.X.Snap(x);
        }
        ClampScroll();
    }

    private int ContentWidth { get { int live = 0; foreach (Tile t in tiles) if (!t.Removing) live++; return live == 0 ? 0 : live * Pitch - (Pitch - TileW); } }
    private int Viewport { get { return Width - Ember.S(28); } }
    private void ClampScroll() { double max = Math.Max(0, ContentWidth - Viewport); if (scrollX.Target > max) scrollX.To(max, 200); }

    private RectangleF TileRect(Tile t)
    {
        return new RectangleF((float)(t.X.Value - scrollX.Value), Ember.Sf(14 + 28 + 10), TileW, TileH);
    }

    private void UpdateParts()
    {
        int pw = clear.PreferredWidth(Ember.S(28));
        clear.Bounds = new Rectangle(Width - Ember.S(10) - pw, Ember.S(14), pw, Ember.S(28));
        clear.Visible = mode.Target > 0.5 && header.Length > 0;
        foreach (Tile t in tiles)
        {
            RectangleF r = TileRect(t);
            int d = Ember.S(20);
            t.Remove.Bounds = new Rectangle((int)(r.Right - d + Ember.S(4)), (int)(r.Top - Ember.S(4)), d, d);
            t.Remove.Visible = !t.Removing && t == hoverTile && r.Right <= Width - Ember.S(10) && r.Left >= Ember.S(8);
        }
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        Tile over = null;
        foreach (Tile t in tiles) if (!t.Removing && RectangleF.Inflate(TileRect(t), Ember.Sf(6), Ember.Sf(6)).Contains(e.Location) && e.X > Ember.S(8) && e.X < Width - Ember.S(8)) over = t;
        if (over != hoverTile)
        {
            if (hoverTile != null) hoverTile.Hover.To(0, 120);
            hoverTile = over;
            if (hoverTile != null) hoverTile.Hover.To(1, 120);
        }
        UpdateParts();
        base.OnMouseMove(e);
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        if (hoverTile != null) hoverTile.Hover.To(0, 120);
        hoverTile = null;
        UpdateParts();
        base.OnMouseLeave(e);
    }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        double max = Math.Max(0, ContentWidth - Viewport);
        if (max > 0 && mode.Target > 0.5)
        {
            double target = Math.Max(0, Math.Min(max, scrollX.Target - e.Delta * Ember.Sf(0.8f)));
            if (Anim.ReduceMotion) scrollX.Snap(target); else scrollX.To(target, 200);
            HandledMouseEventArgs handled = e as HandledMouseEventArgs; if (handled != null) handled.Handled = true;
        }
        base.OnMouseWheel(e);
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); ClampScroll(); }

    protected override void Render(Graphics g)
    {
        UpdateParts();
        float m = (float)mode.Value, d = (float)drag.Value, hv = (float)HoverAnim.Value;
        RectangleF card = new RectangleF(0, 0, Width, Height);
        float radius = Ember.Sf(20);
        // Empty: compact dashed drop zone on the page background.
        if (m < 0.999f)
        {
            double a = 1 - m;
            Color fill = Ember.Mix(Ember.Mix(Color.FromArgb(0, 255, 255, 255), Ember.Fill05, hv), Ember.AccentSoft, d);
            Ember.Fill(g, card, radius, Ember.Ink(fill, BackColor, a));
            float pw = Ember.Sf(1.5f);
            using (GraphicsPath p = Ember.Round(new RectangleF(pw / 2, pw / 2, Width - pw, Height - pw), radius - pw / 2))
            using (Pen pen = new Pen(Ember.Ink(Ember.Mix(Ember.Mix(Ember.Fill20, Color.FromArgb(90, 255, 255, 255), hv), Ember.Accent, d), BackColor, a), pw))
            {
                pen.DashPattern = new float[] { 4f, 3f };
                g.DrawPath(pen, p);
            }
            Font f = Ember.Font(14, 500);
            string label = "Drop files or click to choose";
            float gs = Ember.Sf(22), gap = Ember.Sf(10);
            float tw = Ember.Measure(label, f).Width;
            float x0 = (Width - (gs + gap + tw)) / 2f, cy = Height / 2f;
            Glyphs.Draw(g, Glyph.Upload, new RectangleF(x0, cy - gs / 2, gs, gs), Ember.Ink(Ember.Mix(Ember.TextMuted, Ember.Accent, d), BackColor, a), 0);
            Ember.Draw(g, label, f, Ember.Ink(Ember.Mix(Ember.TextSoft, Color.White, Math.Max(hv, d)), BackColor, a), new RectangleF(x0 + gs + gap, cy - Ember.Sf(12), tw + 4, Ember.Sf(24)), StringAlignment.Near, StringAlignment.Center);
        }
        if (m <= 0.001f) return;
        Color surface = Ember.Ink(Ember.Surface, BackColor, m);
        Ember.Fill(g, card, radius, surface);
        Ember.Stroke(g, card, radius, Ember.Ink(Ember.Mix(Ember.Line, Ember.Accent, d), BackColor, m), d > 0.01f ? Ember.Sf(1.5f) : 1f);
        Ember.Draw(g, header, Ember.Font(15, 600), Ember.Ink(Color.White, surface, m), new RectangleF(Ember.Sf(14), Ember.Sf(14), Width - Ember.Sf(120), Ember.Sf(28)), StringAlignment.Near, StringAlignment.Center);
        if (clear.Visible) DrawPart(g, clear, m, surface);
        GraphicsState state = g.Save();
        g.SetClip(new RectangleF(Ember.Sf(6), 0, Width - Ember.Sf(12), Height));
        foreach (Tile t in tiles) DrawTile(g, t, surface, m);
        g.Restore(state);
        foreach (Tile t in tiles) if (t.Remove.Visible) DrawRemove(g, t, surface);
    }

    private void DrawTile(Graphics g, Tile t, Color surface, double cardAlpha)
    {
        double a = Math.Max(0, Math.Min(1, t.Appear.Value)) * cardAlpha;
        if (a <= 0.002) return;
        RectangleF r = TileRect(t);
        if (r.Right < 0 || r.Left > Width) return;
        float s = Anim.ReduceMotion ? 1f : 0.92f + 0.08f * (float)Math.Min(1, t.Appear.Value);
        RectangleF square = Ember.ScaleAround(new RectangleF(r.X, r.Y, TileW, TileW), s);
        float hv = (float)t.Hover.Value;
        Color tileBg = Ember.Mix(Ember.Over(Ember.Fill07, Ember.Surface), Ember.Over(Ember.Fill12, Ember.Surface), hv);
        if (t.Thumb != null) ImageLoader.DrawCover(g, t.Thumb, square, Ember.Sf(12), a);
        else
        {
            Ember.Fill(g, square, Ember.Sf(12), Ember.Ink(tileBg, surface, a));
            float gs = Ember.Sf(24) * s;
            Color ink = Ember.Ink(Ember.TextMuted, tileBg, a);
            Glyphs.Draw(g, Glyph.File, new RectangleF(square.X + (square.Width - gs) / 2, square.Y + square.Height * 0.2f, gs, gs), ink, 0);
            string ext = (System.IO.Path.GetExtension(t.Path) ?? "").TrimStart('.').ToUpperInvariant();
            if (ext.Length > 5) ext = ext.Substring(0, 5);
            Ember.Draw(g, ext, Ember.Font(9, 700), ink, new RectangleF(square.X, square.Y + square.Height * 0.62f, square.Width, Ember.Sf(14)), StringAlignment.Center, StringAlignment.Center);
        }
        if (hv > 0.01f && t.Thumb != null) Ember.Stroke(g, square, Ember.Sf(12), Ember.Ink(Color.FromArgb((int)(60 * hv), 255, 255, 255), surface, a), 1f);
        Font nf = Ember.Font(11, 500);
        string name = Ember.MiddleTrim(System.IO.Path.GetFileName(t.Path), nf, TileW + Ember.Sf(4));
        Ember.Draw(g, name, nf, Ember.Ink(Ember.TextSoft, surface, a), new RectangleF(r.X - Ember.Sf(4), r.Y + TileW + Ember.Sf(5), TileW + Ember.Sf(8), Ember.Sf(16)), StringAlignment.Center, StringAlignment.Center);
    }

    private void DrawRemove(Graphics g, Tile t, Color surface)
    {
        Part p = t.Remove;
        RectangleF r = Ember.ScaleAround(p.Bounds, 1f - 0.08f * (float)p.Press.Value);
        double a = t.Hover.Value;
        Color bg = Ember.Mix(Color.FromArgb(0x3A, 0x3A, 0x3A), Color.FromArgb(0x55, 0x55, 0x55), (float)p.Hover.Value);
        using (SolidBrush b = new SolidBrush(Ember.Ink(bg, surface, a))) g.FillEllipse(b, r);
        float gs = r.Width * 0.5f;
        Glyphs.Draw(g, Glyph.Close, new RectangleF(r.X + (r.Width - gs) / 2, r.Y + (r.Height - gs) / 2, gs, gs), Ember.Ink(Color.White, surface, a), 0);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) foreach (Tile t in tiles) if (t.Thumb != null) t.Thumb.Dispose();
        base.Dispose(disposing);
    }
}

internal enum BannerState { Hidden, Receiving, Done, Failed }

internal sealed class IncomingBanner : PartHost
{
    private string text = "";
    private BannerState state = BannerState.Hidden;
    private readonly Anim show = new Anim(0);
    private readonly Anim progress = new Anim(0);
    private int hideToken;
    public Action HeightChanged;
    public Action OpenFolder;

    public IncomingBanner()
    {
        show.Changed = delegate { Invalidate(); if (HeightChanged != null) HeightChanged(); };
        show.Finished = delegate { if (show.Value <= 0.001) state = BannerState.Hidden; };
        progress.Changed = Invalidate;
    }

    public int FullHeight { get { return Ember.S(44); } }
    public int CurrentHeight { get { return (int)Math.Round(FullHeight * Math.Max(0, Math.Min(1, show.Value))); } }
    public double Visibility { get { return show.Value; } }

    public override string Text { get { return text; } set { text = value ?? ""; Invalidate(); } }

    public int Progress
    {
        set
        {
            double v = Math.Max(0, Math.Min(1000, value)) / 1000.0;
            if (v < progress.Target) progress.Snap(v); else progress.To(v, 160);
        }
    }

    public void Receiving()
    {
        hideToken++;
        if (state != BannerState.Receiving) { state = BannerState.Receiving; BackgroundClick = null; }
        if (show.Target < 1) show.To(1, Anim.ReduceMotion ? 0 : 220);
        Invalidate();
    }

    public void Finish(bool success)
    {
        state = success ? BannerState.Done : BannerState.Failed;
        if (success) progress.To(1, 160);
        BackgroundClick = success ? (Action)delegate { if (OpenFolder != null) OpenFolder(); } : null;
        if (show.Target < 1) show.To(1, Anim.ReduceMotion ? 0 : 220);
        int token = ++hideToken;
        Ember.Later(3200, delegate { if (token == hideToken && !IsDisposed) { show.To(0, Anim.ReduceMotion ? 0 : 220); BackgroundClick = null; } });
        Invalidate();
    }

    protected override void Render(Graphics g)
    {
        double a = Math.Max(0, Math.Min(1, show.Value));
        if (a <= 0.002 || Height <= 0) return;
        float hv = BackgroundClick != null ? (float)HoverAnim.Value : 0f;
        Color tone = state == BannerState.Done ? Ember.Positive : state == BannerState.Failed ? Ember.Negative : Ember.Accent;
        RectangleF r = new RectangleF(0, 0, Width, FullHeight);
        Color tint = Ember.Over(Color.FromArgb((int)(30 + 14 * hv), tone), Ember.Surface);
        Color surface = Ember.Ink(tint, BackColor, a);
        Ember.Fill(g, r, Ember.Sf(14), surface);
        Ember.Stroke(g, r, Ember.Sf(14), Ember.Ink(Color.FromArgb(50, tone), BackColor, a), 1f);
        float gs = Ember.Sf(17);
        Glyph glyph = state == BannerState.Done ? Glyph.Check : state == BannerState.Failed ? Glyph.Close : Glyph.Download;
        Glyphs.Draw(g, glyph, new RectangleF(Ember.Sf(14), (FullHeight - gs) / 2f - (state == BannerState.Receiving ? Ember.Sf(3) : 0f), gs, gs), Ember.Ink(tone, surface, a), 0);
        float x = Ember.Sf(14) + gs + Ember.Sf(10);
        string trailing = state == BannerState.Done ? "Open folder" : state == BannerState.Receiving ? (int)Math.Round(progress.Value * 100) + "%" : "";
        Font tf = Ember.Font(12, 600);
        float tw = trailing.Length == 0 ? 0 : Ember.Measure(trailing, tf).Width + Ember.Sf(4);
        float lift = state == BannerState.Receiving ? Ember.Sf(3) : 0f;
        Ember.Draw(g, text, Ember.Font(13, 500), Ember.Ink(Color.White, surface, a), new RectangleF(x, -lift, Width - x - tw - Ember.Sf(24), FullHeight), StringAlignment.Near, StringAlignment.Center);
        if (trailing.Length > 0)
            Ember.Draw(g, trailing, tf, Ember.Ink(state == BannerState.Done ? Ember.TextSoft : Ember.TextMuted, surface, a), new RectangleF(Width - Ember.Sf(14) - tw, -lift, tw, FullHeight), StringAlignment.Far, StringAlignment.Center);
        if (state == BannerState.Receiving)
        {
            float lh = Ember.Sf(3);
            RectangleF track = new RectangleF(Ember.Sf(14), FullHeight - lh - Ember.Sf(4), Width - Ember.Sf(28), lh);
            Ember.Fill(g, track, lh / 2, Ember.Ink(Ember.Fill12, surface, a));
            Ember.Fill(g, new RectangleF(track.X, track.Y, Math.Max(lh, (float)(track.Width * progress.Value)), lh), lh / 2, Ember.Ink(Ember.Accent, surface, a));
        }
    }
}

// ---------------------------------------------------------------------------
// Device rows (paired, nearby, send-to) and settings rows
// ---------------------------------------------------------------------------
internal enum RowMode { Idle, Sending, Sent }

internal sealed class DeviceRow : ListRow
{
    public string Title = "", Caption = "";
    public Color CaptionColor = Color.Empty;
    public bool Online;
    public bool Phone;
    public Part ActionPart;
    public Part Star;
    public Part Remove;
    public RowMode Mode = RowMode.Idle;
    public readonly Anim ProgressAnim = new Anim(0);
    public readonly Anim ModeAnim = new Anim(0);
    public object Tag2;
    public int ActionHeight = 30;

    private const float PadX = 9f, Avatar = 34f;

    public DeviceRow()
    {
        FullHeight = Ember.S(52);
        DividerInset = Ember.S(PadX + Avatar + 12);
        ProgressAnim.Changed = Invalidate;
        ModeAnim.Changed = Invalidate;
    }

    public bool SetData(string title, string caption, Color captionColor, bool online, bool phone)
    {
        if (title == Title && caption == Caption && captionColor == CaptionColor && online == Online && phone == Phone) return false;
        Title = title ?? ""; Caption = caption ?? ""; CaptionColor = captionColor; Online = online; Phone = phone;
        Invalidate();
        return true;
    }

    public void SetCaption(string caption) { SetData(Title, caption, CaptionColor, Online, Phone); }

    public void SetMode(RowMode mode)
    {
        if (mode == Mode) return;
        Mode = mode;
        ModeAnim.Snap(0);
        ModeAnim.To(1, Anim.ReduceMotion ? 0 : (mode == RowMode.Sent ? 260 : 180));
        if (mode == RowMode.Sending) ProgressAnim.Snap(0);
        Invalidate();
    }

    public void SetProgress(int value)
    {
        double v = Math.Max(0, Math.Min(1000, value)) / 1000.0;
        if (v < ProgressAnim.Target) ProgressAnim.Snap(v); else ProgressAnim.To(v, 160);
    }

    private int TrailEdge { get { return Width - Ember.S(PadX + 3); } }

    private void LayoutParts()
    {
        int right = TrailEdge;
        int icon = Ember.S(28);
        if (Remove != null)
        {
            Remove.Bounds = new Rectangle(right - icon, (FullHeight - icon) / 2, icon, icon);
            right -= icon + Ember.S(2);
        }
        if (ActionPart != null)
        {
            int h = Ember.S(ActionHeight);
            int w = Math.Max(Ember.S(64), ActionPart.PreferredWidth(h));
            ActionPart.Bounds = new Rectangle(right - w, (FullHeight - h) / 2, w, h);
            ActionPart.Visible = Mode == RowMode.Idle;
            right -= w + Ember.S(6);
        }
        if (Star != null)
        {
            Star.Bounds = new Rectangle(right - icon, (FullHeight - icon) / 2, icon, icon);
            Star.Visible = Mode == RowMode.Idle;
            right -= icon;
        }
    }

    private int TextRight()
    {
        int right = TrailEdge;
        foreach (Part p in Parts) if (p.Bounds.Width > 0) right = Math.Min(right, p.Bounds.Left);
        return right - Ember.S(10);
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); LayoutParts(); }
    protected override void OnMouseMove(MouseEventArgs e) { LayoutParts(); base.OnMouseMove(e); }

    protected override void RenderRow(Graphics g, double alpha)
    {
        LayoutParts();
        Color under = BackColor;
        float av = Ember.Sf(Avatar);
        RectangleF avatar = new RectangleF(Ember.Sf(PadX), (FullHeight - av) / 2f, av, av);
        Glyphs.Avatar(g, avatar, Phone, under, alpha);
        if (Online)
        {
            float d = Ember.Sf(10), ring = Ember.Sf(2);
            RectangleF dot = new RectangleF(avatar.Right - d + Ember.Sf(1), avatar.Bottom - d + Ember.Sf(1), d, d);
            using (SolidBrush b = new SolidBrush(Ember.Ink(Color.FromArgb(255, under), under, 1))) g.FillEllipse(b, dot.X - ring, dot.Y - ring, d + ring * 2, d + ring * 2);
            using (SolidBrush b = new SolidBrush(Ember.Ink(Ember.Positive, under, alpha))) g.FillEllipse(b, dot);
        }
        float x = DividerInset;
        float textRight = TextRight();
        Ember.Draw(g, Title, Ember.Font(15, 500), Ember.Ink(Color.White, under, alpha), new RectangleF(x, FullHeight / 2f - Ember.Sf(19), textRight - x, Ember.Sf(20)), StringAlignment.Near, StringAlignment.Center);
        Color cap = CaptionColor.IsEmpty ? Ember.TextMuted : CaptionColor;
        Ember.Draw(g, Caption, Ember.Font(12, 400), Ember.Ink(cap, under, alpha), new RectangleF(x, FullHeight / 2f + Ember.Sf(1), textRight - x, Ember.Sf(17)), StringAlignment.Near, StringAlignment.Center);
        foreach (Part p in Parts) DrawPart(g, p, alpha);
        if (Mode == RowMode.Idle || ActionPart == null) return;
        double m = ModeAnim.Value;
        float size = Ember.Sf(30);
        RectangleF slot = new RectangleF(TrailEdge - size, (FullHeight - size) / 2f, size, size);
        if (Mode == RowMode.Sending)
        {
            double a = alpha * m;
            float stroke = Ember.Sf(2.5f);
            RectangleF ring = RectangleF.Inflate(slot, -stroke / 2f - Ember.Sf(1), -stroke / 2f - Ember.Sf(1));
            using (Pen track = new Pen(Ember.Ink(Ember.Fill07, under, a), stroke)) g.DrawEllipse(track, ring);
            float sweep = (float)(360.0 * Math.Max(0.02, ProgressAnim.Value));
            using (Pen arc = new Pen(Ember.Ink(Ember.Accent, under, a), stroke))
            {
                arc.StartCap = LineCap.Round; arc.EndCap = LineCap.Round;
                g.DrawArc(arc, ring, -90f, sweep);
            }
            // 3px progress line along the bottom of the row.
            float lh = Ember.Sf(3);
            RectangleF line = new RectangleF(x, FullHeight - lh - Ember.Sf(1), Width - x - Ember.Sf(PadX + 3), lh);
            Ember.Fill(g, line, lh / 2f, Ember.Ink(Ember.Fill07, under, a));
            Ember.Fill(g, new RectangleF(line.X, line.Y, Math.Max(lh, (float)(line.Width * ProgressAnim.Value)), lh), lh / 2f, Ember.Ink(Ember.Accent, under, a));
        }
        else if (Mode == RowMode.Sent)
        {
            float s = Anim.ReduceMotion ? 1f : (float)(0.6 + 0.4 * Math.Min(1, m * 1.15));
            RectangleF circle = Ember.ScaleAround(RectangleF.Inflate(slot, -Ember.Sf(2), -Ember.Sf(2)), s);
            using (SolidBrush b = new SolidBrush(Ember.Ink(Ember.Positive, under, alpha * Math.Min(1, m * 1.5)))) g.FillEllipse(b, circle);
            Glyphs.Draw(g, Glyph.Check, RectangleF.Inflate(circle, -circle.Width * 0.22f, -circle.Height * 0.22f), Ember.Ink(Color.FromArgb(0x0E, 0x2A, 0x16), Ember.Positive, alpha * m), 0);
        }
    }
}

// Settings row: title + caption + trailing control (button part or toggle).
internal sealed class SettingRow : PartHost
{
    public string Title = "", Caption = "";
    public Color TitleColor = Color.White;
    public bool CaptionMono, CaptionPath, ShowDivider;
    public Part ActionPart;
    public ToggleSwitch Toggle;

    public SettingRow(string title, string caption)
    {
        Title = title; Caption = caption ?? "";
        BackColor = Ember.Surface;
        Height = RowHeight;
    }

    public int RowHeight { get { return Ember.S(48); } }

    public Part SetAction(string text, PartKind kind, Action click)
    {
        ActionPart = AddPart(new Part(kind, text, Glyph.None));
        ActionPart.Click = click;
        return ActionPart;
    }

    public ToggleSwitch SetToggle()
    {
        Toggle = new ToggleSwitch();
        Toggle.BackColor = Ember.Surface;
        Controls.Add(Toggle);
        return Toggle;
    }

    public void SetCaption(string caption) { if (caption == Caption) return; Caption = caption ?? ""; Invalidate(); }

    private int TrailingLeft()
    {
        int right = Width - Ember.S(9);
        if (ActionPart != null)
        {
            int h = Ember.S(30);
            int w = Math.Max(Ember.S(72), ActionPart.PreferredWidth(h));
            ActionPart.Bounds = new Rectangle(right - w, (Height - h) / 2, w, h);
            return ActionPart.Bounds.Left;
        }
        if (Toggle != null)
        {
            Toggle.Location = new Point(right - Toggle.Width, (Height - Toggle.Height) / 2);
            return Toggle.Left;
        }
        return right;
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); TrailingLeft(); }
    protected override void OnMouseMove(MouseEventArgs e) { TrailingLeft(); base.OnMouseMove(e); }

    protected override void Render(Graphics g)
    {
        int left = Ember.S(9);
        int textRight = TrailingLeft() - Ember.S(16);
        if (ShowDivider)
            using (SolidBrush b = new SolidBrush(Ember.Ink(Ember.Line, BackColor, 1))) g.FillRectangle(b, left, 0, Width - left * 2, Math.Max(1, (int)Math.Floor(Ember.Scale)));
        bool hasCaption = !String.IsNullOrEmpty(Caption);
        float titleY = hasCaption ? Height / 2f - Ember.Sf(19) : (Height - Ember.Sf(20)) / 2f;
        Ember.Draw(g, Title, Ember.Font(15, 500), Ember.Ink(TitleColor, BackColor, 1), new RectangleF(left, titleY, textRight - left, Ember.Sf(20)), StringAlignment.Near, StringAlignment.Center);
        if (hasCaption)
            Ember.Draw(g, Caption, CaptionMono ? Ember.Mono(12) : Ember.Font(12, 400), Ember.Ink(Ember.TextMuted, BackColor, 1), new RectangleF(left, Height / 2f + Ember.Sf(1), textRight - left, Ember.Sf(17)), StringAlignment.Near, StringAlignment.Center, false, CaptionPath ? StringTrimming.EllipsisPath : StringTrimming.EllipsisCharacter);
        foreach (Part p in Parts) DrawPart(g, p, 1.0);
    }
}

// ---------------------------------------------------------------------------
// Engine runtime (unchanged behaviour)
// ---------------------------------------------------------------------------
internal sealed class CliResult
{
    public int ExitCode;
    public string Output = "";
    public string Error = "";
}

internal sealed class PeerState
{
    public string Id = "";
    public string Name = "";
    public ulong LastSeenMs;
}

internal sealed class UiState
{
    public string DeviceId = "";
    public string DeviceName = "Windows PC";
    public string SpaceId = "";
    public bool SendEnabled = true;
    public bool ReceiveEnabled = true;
    public readonly List<PeerState> Peers = new List<PeerState>();
}

internal static class ClipMeshRuntime
{
    private const string Version = "0.2.11";

    public static string AppVersion { get { return Version; } }

    public static string RuntimeDirectory
    {
        get
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ClipMesh", "Runtime", Version);
        }
    }

    public static string EnginePath { get { return Path.Combine(RuntimeDirectory, "clipmesh-bin.exe"); } }

    public static string LogPath
    {
        get
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ClipMesh", "clipmesh.log");
        }
    }

    // Directory holding config.json and peers.json (watched by the UI instead of polling).
    public static string ConfigDirectory
    {
        get
        {
            try
            {
                foreach (string candidate in ConfigCandidates) if (File.Exists(candidate)) return Path.GetDirectoryName(candidate);
                return Path.GetDirectoryName(ConfigCandidates[0]);
            }
            catch { return null; }
        }
    }

    private static string[] ConfigCandidates
    {
        get
        {
            string roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            return new string[]
            {
                Path.Combine(roaming, "ClipMesh", "ClipMesh", "config", "config.json"),
                Path.Combine(roaming, "ClipMesh", "ClipMesh", "config.json")
            };
        }
    }

    public static void EnsureEngine()
    {
        Directory.CreateDirectory(RuntimeDirectory);
        string temp = EnginePath + ".new";
        using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("ClipMesh.Engine"))
        {
            if (source == null) throw new InvalidOperationException("The embedded ClipMesh sync engine is missing.");
            using (FileStream target = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
                source.CopyTo(target);
        }
        if (File.Exists(EnginePath)) File.Delete(EnginePath);
        File.Move(temp, EnginePath);
    }

    public static CliResult Run(params string[] arguments)
    {
        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = EnginePath;
        start.Arguments = JoinArguments(arguments);
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        using (Process process = Process.Start(start))
        {
            if (process == null) throw new InvalidOperationException("Could not start the ClipMesh sync engine.");
            string output = process.StandardOutput.ReadToEnd();
            string error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            return new CliResult { ExitCode = process.ExitCode, Output = output, Error = error };
        }
    }

    public static string Checked(string message, params string[] arguments)
    {
        CliResult result = Run(arguments);
        if (result.ExitCode != 0)
            throw new InvalidOperationException(message + Environment.NewLine + PreferredError(result));
        return result.Output.Trim();
    }

    public static void PrepareFirstRun()
    {
        EnsureEngine();
        CliResult status = Run("status");
        if (status.ExitCode == 0) return;

        string detail = (status.Error + "\n" + status.Output).Trim();
        bool missingKey = Contains(detail, "read space key from OS keyring") ||
                          Contains(detail, "No matching entry found in secure storage");
        bool missingConfig = Contains(detail, "config.json") &&
                             (Contains(detail, "os error 2") || Contains(detail, "cannot find the file") ||
                              Contains(detail, "cannot find the path") || Contains(detail, "No such file or directory"));

        if (missingKey)
        {
            bool moved = false;
            foreach (string config in ConfigCandidates)
            {
                if (!File.Exists(config)) continue;
                string backup = config + ".unrecoverable-v0.1.1-" + DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ".bak";
                File.Move(config, backup);
                moved = true;
                break;
            }
            if (!moved)
                throw new InvalidOperationException("ClipMesh found an unusable v0.1.1 encryption key state, but could not locate config.json to repair it.\n" + detail);
        }
        else if (!missingConfig)
        {
            throw new InvalidOperationException("ClipMesh could not read its current configuration.\n" + detail);
        }

        Checked("Could not initialize ClipMesh.", "init", "--name", Environment.MachineName);
        Checked("ClipMesh initialized, but its secure key could not be loaded.", "status");
    }

    public static string PairingLink()
    {
        return Checked("Could not create the pairing code.", "pairing-uri");
    }

    public static void SeedPeer(string id, string name)
    {
        Checked("Could not save the paired device.", "seed-peer", id, "--name", name);
    }

    public static void ForgetPeer(string id)
    {
        Checked("Could not remove this paired device.", "forget-peer", id);
    }

    public static void SetName(string name)
    {
        Checked("Could not rename this device.", "set-name", "--name", name);
    }

    public static void SetSync(bool send, bool receive)
    {
        Checked("Could not save sync settings.", "set-sync", "--send", send ? "true" : "false", "--receive", receive ? "true" : "false");
    }

    public static void JoinSpace(string uri, string name)
    {
        Checked("Could not join that ClipMesh space.", "join", uri, "--name", name, "--replace");
    }

    public static void NewSpace(string name)
    {
        Checked("Could not create a new ClipMesh space.", "new-space", "--name", name);
    }

    public static void ResetIdentity(string name)
    {
        Checked("Could not reset ClipMesh pairing.", "reset", "--name", name);
    }

    public static UiState GetUiState()
    {
        string output = Checked("Could not read ClipMesh state.", "ui-state");
        UiState state = new UiState();
        string[] lines = output.Replace("\r", "").Split('\n');
        foreach (string line in lines)
        {
            if (String.IsNullOrWhiteSpace(line)) continue;
            string[] parts = line.Split('\t');
            if (parts.Length == 0) continue;
            if (parts[0] == "DEVICE" && parts.Length >= 3)
            {
                state.DeviceId = parts[1];
                state.DeviceName = parts[2];
            }
            else if (parts[0] == "SPACE" && parts.Length >= 2)
            {
                state.SpaceId = parts[1];
            }
            else if (parts[0] == "SYNC" && parts.Length >= 3)
            {
                bool send, receive;
                if (Boolean.TryParse(parts[1], out send)) state.SendEnabled = send;
                if (Boolean.TryParse(parts[2], out receive)) state.ReceiveEnabled = receive;
            }
            else if (parts[0] == "PEER" && parts.Length >= 4)
            {
                ulong seen = 0;
                UInt64.TryParse(parts[2], out seen);
                state.Peers.Add(new PeerState { Id = parts[1], LastSeenMs = seen, Name = parts[3] });
            }
        }
        if (String.IsNullOrWhiteSpace(state.DeviceId) || String.IsNullOrWhiteSpace(state.SpaceId))
            throw new InvalidOperationException("ClipMesh returned incomplete device state.");
        return state;
    }

    public static Process StartDaemon(Action<string> logLine, Action<Process, int> exited)
    {
        string logDir = Path.GetDirectoryName(LogPath);
        if (!String.IsNullOrEmpty(logDir)) Directory.CreateDirectory(logDir);
        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = EnginePath;
        start.Arguments = "run";
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        Process process = new Process();
        process.StartInfo = start;
        process.EnableRaisingEvents = true;
        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) logLine(e.Data); };
        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) logLine(e.Data); };
        process.Exited += delegate { exited(process, process.ExitCode); };
        if (!process.Start()) throw new InvalidOperationException("Could not start ClipMesh in the background.");
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return process;
    }

    private static bool Contains(string value, string needle)
    {
        return value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static string PreferredError(CliResult result)
    {
        return String.IsNullOrWhiteSpace(result.Error) ? result.Output.Trim() : result.Error.Trim();
    }

    private static string JoinArguments(string[] args)
    {
        string[] quoted = new string[args.Length];
        for (int i = 0; i < args.Length; i++) quoted[i] = Quote(args[i]);
        return String.Join(" ", quoted);
    }

    private static string Quote(string value)
    {
        if (value.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0) return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}

// Muted single line with an optional softly pulsing dot (empty states).
internal sealed class PulseLabel : EmberControl
{
    private string text;
    public bool Pulse;
    private readonly Func<bool> ticker;
    private double pulseStart;
    private const double PulseMs = 8000; // pulse briefly, then rest (no endless repaint).

    public PulseLabel(string value, bool pulse)
    {
        text = value; Pulse = pulse;
        BackColor = Ember.Surface;
        Height = Ember.S(28);
        ticker = delegate { if (IsDisposed || !Visible || !Pulse) return false; Invalidate(); return Anim.Now - pulseStart < PulseMs; };
    }

    public override string Text { get { return text; } set { text = value ?? ""; Invalidate(); } }

    protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); if (Visible && Pulse && !Anim.ReduceMotion) { pulseStart = Anim.Now; Anim.AddTicker(ticker); } }

    protected override void Render(Graphics g)
    {
        float x = 0;
        if (Pulse)
        {
            double elapsed = Anim.Now - pulseStart;
            double phase = Anim.ReduceMotion || elapsed >= PulseMs ? 1 : 0.35 + 0.65 * (0.5 + 0.5 * Math.Cos(elapsed / 420.0));
            float d = Ember.Sf(8);
            float halo = d * (Anim.ReduceMotion ? 1f : 1f + 0.9f * (float)(1 - phase));
            float cx = Ember.Sf(6), cy = Height / 2f;
            using (SolidBrush b = new SolidBrush(Ember.Ink(Color.FromArgb(60, Ember.Accent), BackColor, 1 - phase * 0.6))) g.FillEllipse(b, cx - halo / 2, cy - halo / 2, halo, halo);
            using (SolidBrush b = new SolidBrush(Ember.Ink(Ember.Accent, BackColor, 0.5 + 0.5 * phase))) g.FillEllipse(b, cx - d / 2, cy - d / 2, d, d);
            x = Ember.Sf(22);
        }
        Ember.Draw(g, text, Ember.Font(14, 400), Ember.Ink(Ember.TextMuted, BackColor, 1), new RectangleF(x, 0, Width - x, Height), StringAlignment.Near, StringAlignment.Center);
    }
}

internal enum SyncStatus { Starting, On, Recovering, Stopped }

// ---------------------------------------------------------------------------
// Main window
// ---------------------------------------------------------------------------
internal sealed class ClipMeshForm : Form
{
    private const int WM_CLIPBOARDUPDATE = 0x031D;

    private readonly bool snapshotMode;
    private HashSet<string> snapshotTrusted;
    private readonly NotifyIcon tray;
    private readonly Icon trayIcon;
    private readonly Sidebar sidebar;
    private readonly EmberPanel pageHost;
    private readonly ScrollPage[] pages = new ScrollPage[3];
    private readonly PageTransition transition;

    // Clipboard page
    private readonly TextView clipboardTitle;
    private readonly TextView deviceLine;
    private readonly StatusPill statusPill;
    private readonly ClipboardCard clipboardCard;
    private readonly Card devicesCard;
    private readonly TextView devicesTitle;
    private readonly PillButton refreshDevices;
    private readonly PillButton pairWithCode;
    private readonly RowList pairedList;
    private readonly RowList nearbyList;
    private readonly TextView nearbyHeader;
    private readonly PulseLabel devicesEmpty;

    // Transfer page
    private readonly TextView transferTitle;
    private readonly PillButton chooseFiles;
    private readonly IncomingBanner transferStatus;
    private readonly SelectionCard selectionCard;
    private readonly Card sendCard;
    private readonly TextView sendTitle;
    private readonly RowList transferDeviceList;
    private readonly PulseLabel sendEmpty;

    // Settings page
    private readonly TextView settingsTitle;
    private readonly List<Control[]> settingsSections = new List<Control[]>();
    private readonly SettingRow nameRow, idRow, sendRow, receiveRow, folderRow, favoritesRow, pairCodeRow, copyCodeRow, newSpaceRow, resetRow, explorerRow;
    private readonly ToggleSwitch settingsSend;
    private readonly ToggleSwitch settingsReceive;
    private readonly TextView footer;

    // Event-driven refresh (no polling): engine DevicesChanged, peers.json/config.json watcher, one-shot timers.
    private readonly System.Windows.Forms.Timer shareTimer;
    private readonly System.Windows.Forms.Timer peersDebounce;
    private readonly System.Windows.Forms.Timer configDebounce;
    private readonly System.Windows.Forms.Timer onlineTimer;
    private FileSystemWatcher configWatcher;
    private bool devicesSubscribed;
    private bool startupDone;

    private readonly List<string> transferFiles = new List<string>();
    private int selectedTab;
    private readonly object logLock = new object();
    private Process daemon;
    private bool quitting;
    private UiState latestState;
    private Form pairingCodeWindow;
    private string pairingKey;
    private string sendingKey;
    private string sendingCaption;
    private int sendingIndex, sendingCount, sendingPercent;
    private int refreshToken;
    private int syncToken;
    private bool syncPending;
    private uint lastClipboardSequence = UInt32.MaxValue;
    private bool clipboardRefreshQueued;
    private bool viewerOpen;
    private bool clipboardListener;
    private bool balloonOpensFolder;
    private int lastIncomingBalloonPercent = -100;

    private const int PagePad = 24, PageTop = 20, TitleH = 32, CardGap = 12;

    public ClipMeshForm() : this(false) { }

    public ClipMeshForm(bool snapshot)
    {
        snapshotMode = snapshot;
        Ember.Init();
        Text = "ClipMesh";
        AutoScaleMode = AutoScaleMode.None;
        Rectangle work = Screen.PrimaryScreen.WorkingArea;
        if (snapshot)
        {
            MinimumSize = new Size(Ember.S(820), Ember.S(580));
            Size = new Size(Ember.S(1000), Ember.S(700));
        }
        else
        {
            MinimumSize = new Size(Math.Min(Ember.S(780), work.Width - 40), Math.Min(Ember.S(540), work.Height - 40));
            Size = new Size(Math.Min(Ember.S(1000), work.Width - 40), Math.Min(Ember.S(700), work.Height - 40));
        }
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Ember.Bg;
        ForeColor = Ember.Text;
        DoubleBuffered = true;
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        AllowDrop = true;

        sidebar = new Sidebar();
        sidebar.Dock = DockStyle.Left;
        sidebar.Width = Ember.S(196);
        sidebar.Version = ClipMeshRuntime.AppVersion;
        sidebar.Selected = delegate(int index) { SwitchTab(index); };
        Controls.Add(sidebar);

        pageHost = new EmberPanel();
        pageHost.Dock = DockStyle.Fill;
        Controls.Add(pageHost);
        pageHost.BringToFront();

        transition = new PageTransition();
        transition.Dock = DockStyle.Fill;
        pageHost.Controls.Add(transition);

        for (int i = 0; i < 3; i++)
        {
            ScrollPage page = new ScrollPage();
            page.Dock = DockStyle.Fill;
            page.Visible = false;
            pages[i] = page;
            pageHost.Controls.Add(page);
        }

        // ----- Clipboard page -----
        Panel clip = pages[0].Content;
        clipboardTitle = PageTitle("Clipboard"); clip.Controls.Add(clipboardTitle);
        deviceLine = new TextView("This device · " + Environment.MachineName, Ember.Font(13, 400), Ember.TextMuted); deviceLine.BackColor = Ember.Bg; clip.Controls.Add(deviceLine);
        statusPill = new StatusPill(); statusPill.BackColor = Ember.Bg; statusPill.Clicked = delegate { RestartSync(); }; clip.Controls.Add(statusPill);
        clipboardCard = new ClipboardCard(); clipboardCard.BackColor = Ember.Bg;
        clipboardCard.HeightChanged = delegate { pages[0].RequestLayout(); };
        clipboardCard.BackgroundClick = delegate { viewerOpen = true; try { ClipboardViewer.Show(this, clipboardCard.Content); } finally { viewerOpen = false; } RefreshClipboardPreview(false); };
        clip.Controls.Add(clipboardCard);

        devicesCard = new Card(); clip.Controls.Add(devicesCard);
        devicesTitle = CardHeader("Devices"); devicesCard.Controls.Add(devicesTitle);
        refreshDevices = IconButton(Glyph.Refresh, "Look for devices"); refreshDevices.Click += delegate { ProbePeers(); LocalTransferManagerC.Shared.DiscoverNow(); RefreshHome(); RefreshDeviceLists(); };
        pairWithCode = IconButton(Glyph.Plus, "Pair with a code"); pairWithCode.Click += delegate { PairWithCode(); };
        devicesCard.Controls.Add(refreshDevices); devicesCard.Controls.Add(pairWithCode);
        pairedList = new RowList(); pairedList.HeightChanged += delegate { pages[0].RequestLayout(); }; devicesCard.Controls.Add(pairedList);
        devicesEmpty = new PulseLabel("No paired devices yet", false); devicesCard.Controls.Add(devicesEmpty);
        nearbyHeader = new TextView("Nearby", Ember.Font(12, 500), Ember.TextMuted); nearbyHeader.BackColor = Ember.Surface; devicesCard.Controls.Add(nearbyHeader);
        nearbyList = new RowList(); nearbyList.HeightChanged += delegate { pages[0].RequestLayout(); }; devicesCard.Controls.Add(nearbyList);
        pages[0].Arrange = ArrangeClipboardPage;

        // ----- Transfer page -----
        Panel tp = pages[1].Content;
        transferTitle = PageTitle("Transfer"); tp.Controls.Add(transferTitle);
        chooseFiles = new PillButton("Choose files", PartKind.Secondary); chooseFiles.BackColor = Ember.Bg; chooseFiles.Height = Ember.S(30); chooseFiles.Width = chooseFiles.PreferredWidth; chooseFiles.Click += delegate { ChooseTransferFiles(); }; tp.Controls.Add(chooseFiles);
        transferStatus = new IncomingBanner(); transferStatus.BackColor = Ember.Bg; transferStatus.HeightChanged = delegate { pages[1].RequestLayout(); }; transferStatus.OpenFolder = OpenOutputFolder; tp.Controls.Add(transferStatus);
        selectionCard = new SelectionCard(); selectionCard.BackColor = Ember.Bg;
        selectionCard.HeightChanged = delegate { pages[1].RequestLayout(); };
        selectionCard.Choose = ChooseTransferFiles;
        selectionCard.RemoveFile = delegate(string path) { transferFiles.RemoveAll(delegate(string p) { return String.Equals(p, path, StringComparison.OrdinalIgnoreCase); }); UpdateTransferFiles(); };
        selectionCard.ClearAll = delegate { transferFiles.Clear(); UpdateTransferFiles(); };
        tp.Controls.Add(selectionCard);
        sendCard = new Card(); tp.Controls.Add(sendCard);
        sendTitle = CardHeader("Send to"); sendCard.Controls.Add(sendTitle);
        transferDeviceList = new RowList(); transferDeviceList.HeightChanged += delegate { pages[1].RequestLayout(); }; sendCard.Controls.Add(transferDeviceList);
        sendEmpty = new PulseLabel("Looking for devices on this network…", true); sendCard.Controls.Add(sendEmpty);
        pages[1].Arrange = ArrangeTransferPage;

        // ----- Settings page -----
        Panel sp = pages[2].Content;
        settingsTitle = PageTitle("Settings"); sp.Controls.Add(settingsTitle);
        nameRow = new SettingRow("Device name", Environment.MachineName); nameRow.SetAction("Rename", PartKind.Secondary, delegate { RenameDevice(); });
        idRow = new SettingRow("Device ID", "…"); idRow.CaptionMono = true;
        AddSection("This device", nameRow, idRow);
        sendRow = new SettingRow("Send clipboard", "Share what you copy on this PC"); settingsSend = sendRow.SetToggle(); settingsSend.SetChecked(true, false);
        receiveRow = new SettingRow("Receive clipboard", "Apply what you copy on your other devices"); settingsReceive = receiveRow.SetToggle(); settingsReceive.SetChecked(true, false);
        settingsSend.CheckedChanged += delegate { ApplySyncToggles(); };
        settingsReceive.CheckedChanged += delegate { ApplySyncToggles(); };
        AddSection("Clipboard", sendRow, receiveRow);
        folderRow = new SettingRow("Receive folder", LocalTransferManagerC.Shared.OutputFolder); folderRow.CaptionPath = true; folderRow.SetAction("Change", PartKind.Secondary, delegate { ChooseOutputFolder(); });
        favoritesRow = new SettingRow("Trusted devices", "Star a device on Transfer so it can send without asking");
        AddSection("File transfer", folderRow, favoritesRow);
        pairCodeRow = new SettingRow("Pair with a code", "Paste a code from your other device"); pairCodeRow.SetAction("Pair", PartKind.Secondary, delegate { PairWithCode(); });
        copyCodeRow = new SettingRow("Copy my pairing code", "Share it only with your own devices"); copyCodeRow.SetAction("Copy", PartKind.Secondary, delegate { CopyPairingLink(); });
        newSpaceRow = new SettingRow("Create new private space", "Start over with a new encryption key"); newSpaceRow.SetAction("Create", PartKind.Secondary, delegate { CreateNewSpace(); });
        resetRow = new SettingRow("Reset all pairing", "Forget every device and create a new identity"); resetRow.TitleColor = Ember.Negative;
        resetRow.SetAction("Reset", PartKind.Destructive, delegate { ResetPairing(); });
        AddSection("Pairing", pairCodeRow, copyCodeRow, newSpaceRow, resetRow);
        explorerRow = new SettingRow("Explorer integration", "Send to and right-click menu"); explorerRow.SetAction("Repair", PartKind.Secondary, delegate { RepairExplorerIntegration(); });
        AddSection("Windows", explorerRow);
        footer = new TextView("ClipMesh " + ClipMeshRuntime.AppVersion + " · Clipboard sync is end-to-end encrypted. Files go directly between your devices.", Ember.Font(12, 400), Ember.TextFaint);
        footer.BackColor = Ember.Bg; footer.Wrap = true; footer.Align = StringAlignment.Center; footer.VAlign = StringAlignment.Near; footer.Trimming = StringTrimming.None;
        sp.Controls.Add(footer);
        pages[2].Arrange = ArrangeSettingsPage;

        // ----- Tray -----
        ContextMenuStrip menu = new ContextMenuStrip();
        menu.Renderer = new DarkMenuRenderer();
        menu.BackColor = Color.FromArgb(0x26, 0x26, 0x26);
        menu.ForeColor = Ember.TextSoft;
        menu.Font = Ember.Font(13, 400);
        menu.ShowImageMargin = false;
        menu.Opening += delegate { EmberNative.DarkChrome(menu.Handle, true); };
        ToolStripMenuItem show = new ToolStripMenuItem("Show ClipMesh"); show.Click += delegate { RestoreFromTray(); }; menu.Items.Add(show);
        ToolStripMenuItem sendMenu = new ToolStripMenuItem("Send files…"); sendMenu.Click += delegate { OpenFileSender(); }; menu.Items.Add(sendMenu);
        ToolStripMenuItem copy = new ToolStripMenuItem("Copy pairing code"); copy.Click += delegate { CopyPairingLink(); }; menu.Items.Add(copy);
        menu.Items.Add(new ToolStripSeparator());
        ToolStripMenuItem quit = new ToolStripMenuItem("Quit ClipMesh"); quit.Click += delegate { QuitCompletely(); }; menu.Items.Add(quit);
        foreach (ToolStripItem item in menu.Items) { item.ForeColor = Ember.TextSoft; item.Padding = new Padding(Ember.S(6), Ember.S(4), Ember.S(6), Ember.S(4)); }
        trayIcon = CreateTrayIcon(); tray = new NotifyIcon(); tray.Icon = trayIcon; tray.Text = "ClipMesh"; tray.Visible = !snapshot; tray.ContextMenuStrip = menu;
        tray.MouseClick += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) RestoreFromTray(); };
        tray.BalloonTipClicked += delegate { if (balloonOpensFolder) OpenOutputFolder(); else RestoreFromTray(); };

        shareTimer = OneShot(400, delegate { ProcessShareInbox(); });
        peersDebounce = OneShot(250, delegate { LoadPeersFile(); });
        configDebounce = OneShot(250, delegate { RefreshHome(true); });
        onlineTimer = OneShot(1000, delegate { if (observersAttached) ProbePeers(); else if (latestState != null) RenderPeers(latestState.Peers); });

        DragEnter += FileDragEnter; DragOver += FileDragEnter; DragLeave += delegate { selectionCard.DragHot = false; }; DragDrop += FileDragDrop;
        FormClosing += OnFormClosing; Shown += OnShown;
        Resize += delegate { UpdateObservers(); };
        SetStatus(SyncStatus.Starting);
        UpdateTransferFiles();
        SwitchTab(0);
    }

    // A stopped-after-firing timer: used only to debounce events or schedule a single deadline (never polling).
    private static System.Windows.Forms.Timer OneShot(int interval, Action tick)
    {
        System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        timer.Interval = interval;
        timer.Tick += delegate { timer.Stop(); tick(); };
        return timer;
    }

    private static void Restart(System.Windows.Forms.Timer timer) { timer.Stop(); timer.Start(); }

    // ----- construction helpers -----
    private static TextView PageTitle(string text)
    {
        TextView t = new TextView(text, Ember.Font(24, 600), Ember.Text); t.BackColor = Ember.Bg; return t;
    }

    private static TextView CardHeader(string text)
    {
        TextView t = new TextView(text, Ember.Font(13, 500), Ember.TextMuted); t.BackColor = Ember.Surface; return t;
    }

    private static PillButton IconButton(Glyph glyph, string tip)
    {
        PillButton b = new PillButton("", PartKind.Icon, glyph); b.Tip = tip; b.BackColor = Ember.Surface; b.Part.GlyphSize = 16; b.Size = new Size(Ember.S(28), Ember.S(28)); return b;
    }

    private void AddSection(string title, params SettingRow[] rows)
    {
        Card card = new Card();
        TextView header = CardHeader(title);
        card.Controls.Add(header);
        foreach (SettingRow row in rows) card.Controls.Add(row);
        pages[2].Content.Controls.Add(card);
        Control[] entry = new Control[rows.Length + 2];
        entry[0] = header; entry[1] = card;
        for (int i = 0; i < rows.Length; i++) entry[i + 2] = rows[i];
        settingsSections.Add(entry);
    }

    private static void Place(Control c, int x, int y, int w, int h)
    {
        Rectangle r = new Rectangle(x, y, Math.Max(0, w), Math.Max(0, h));
        if (c.Bounds != r) c.Bounds = r;
    }

    private int ColumnWidth(int width) { return Math.Max(Ember.S(320), Math.Min(width - Ember.S(PagePad * 2), Ember.S(880))); }

    private int PageHeader(TextView title, Control trailing, int width)
    {
        int x = Ember.S(PagePad), w = ColumnWidth(width), y = Ember.S(PageTop), h = Ember.S(TitleH);
        Place(title, x, y, w - trailing.Width - Ember.S(12), h);
        Place(trailing, x + w - trailing.Width, y + (h - trailing.Height) / 2, trailing.Width, trailing.Height);
        return y + h;
    }

    // ----- layout -----
    private int ArrangeClipboardPage(int width)
    {
        int x = Ember.S(PagePad), w = ColumnWidth(width);
        int y = PageHeader(clipboardTitle, statusPill, width);
        Place(deviceLine, x, y, w, Ember.S(18));
        y += Ember.S(18) + Ember.S(14);
        Place(clipboardCard, x, y, w, clipboardCard.CurrentHeight);
        y += clipboardCard.CurrentHeight + Ember.S(CardGap);

        int inset = Ember.S(5), cy = Ember.S(10), bs = Ember.S(28);
        Place(devicesTitle, Ember.S(14), cy, w - Ember.S(100), bs);
        Place(pairWithCode, w - Ember.S(10) - bs, cy, bs, bs);
        Place(refreshDevices, w - Ember.S(10) - bs * 2 - Ember.S(2), cy, bs, bs);
        cy += bs + Ember.S(2);
        Place(pairedList, inset, cy, w - inset * 2, pairedList.ContentHeight);
        cy += pairedList.ContentHeight;
        bool noPaired = pairedList.Count == 0 && pairedList.ContentHeight == 0;
        devicesEmpty.Visible = noPaired;
        if (noPaired) { Place(devicesEmpty, Ember.S(14), cy, w - Ember.S(28), Ember.S(26)); cy += Ember.S(30); }
        bool hasNearby = nearbyList.ContentHeight > 0;
        nearbyHeader.Visible = hasNearby;
        nearbyList.Visible = hasNearby;
        if (hasNearby)
        {
            cy += Ember.S(6);
            Place(nearbyHeader, Ember.S(14), cy, w - Ember.S(28), Ember.S(18));
            cy += Ember.S(20);
            Place(nearbyList, inset, cy, w - inset * 2, nearbyList.ContentHeight);
            cy += nearbyList.ContentHeight;
        }
        cy += Ember.S(6);
        Place(devicesCard, x, y, w, cy);
        return y + cy + Ember.S(PagePad);
    }

    private int ArrangeTransferPage(int width)
    {
        int x = Ember.S(PagePad), w = ColumnWidth(width);
        int y = PageHeader(transferTitle, chooseFiles, width) + Ember.S(14);
        int bh = transferStatus.CurrentHeight;
        transferStatus.Visible = bh > 0;
        if (bh > 0) { Place(transferStatus, x, y, w, bh); y += bh + (int)Math.Round(Ember.S(CardGap) * Math.Min(1, transferStatus.Visibility)); }
        Place(selectionCard, x, y, w, selectionCard.CurrentHeight);
        y += selectionCard.CurrentHeight + Ember.S(CardGap);

        int inset = Ember.S(5), cy = Ember.S(10);
        Place(sendTitle, Ember.S(14), cy, w - Ember.S(28), Ember.S(28));
        cy += Ember.S(30);
        Place(transferDeviceList, inset, cy, w - inset * 2, transferDeviceList.ContentHeight);
        cy += transferDeviceList.ContentHeight;
        bool empty = transferDeviceList.Count == 0 && transferDeviceList.ContentHeight == 0;
        sendEmpty.Visible = empty;
        if (empty) { Place(sendEmpty, Ember.S(14), cy, w - Ember.S(28), Ember.S(26)); cy += Ember.S(30); }
        cy += Ember.S(6);
        Place(sendCard, x, y, w, cy);
        return y + cy + Ember.S(PagePad);
    }

    private int ArrangeSettingsPage(int width)
    {
        int x = Ember.S(PagePad), w = ColumnWidth(width), y = Ember.S(PageTop);
        Place(settingsTitle, x, y, w, Ember.S(TitleH));
        y += Ember.S(TitleH) + Ember.S(14);
        int inset = Ember.S(5);
        foreach (Control[] section in settingsSections)
        {
            int cy = Ember.S(12);
            Place(section[0], Ember.S(14), cy, w - Ember.S(28), Ember.S(18));
            cy += Ember.S(20);
            for (int i = 2; i < section.Length; i++)
            {
                SettingRow row = (SettingRow)section[i];
                row.ShowDivider = i > 2;
                Place(row, inset, cy, w - inset * 2, row.RowHeight);
                cy += row.RowHeight;
            }
            cy += Ember.S(4);
            Place(section[1], x, y, w, cy);
            y += cy + Ember.S(CardGap);
        }
        int fh = footer.PreferredHeightFor(w, 3);
        Place(footer, x, y + Ember.S(4), w, fh);
        return y + fh + Ember.S(PagePad);
    }

    // ----- navigation -----
    private void SwitchTab(int index)
    {
        if (index < 0 || index >= pages.Length) return;
        int previous = selectedTab;
        bool animate = !snapshotMode && IsHandleCreated && Visible && WindowState != FormWindowState.Minimized && previous != index && pages[previous].Visible;
        selectedTab = index;
        sidebar.Select(index, IsHandleCreated && Visible);
        if (transition.Active) transition.Cancel();
        Bitmap old = animate ? Ember.Snapshot(pages[previous]) : null;
        if (old != null) transition.Cover(old);

        if (index == 0) { LocalTransferManagerC.Shared.DiscoverNow(); RefreshNearbyPairDevices(); if (latestState != null) RenderPeers(latestState.Peers); RefreshClipboardPreview(false); }
        if (index == 1) { LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); }
        if (index == 2) { if (latestState != null && !syncPending) { settingsSend.SetChecked(latestState.SendEnabled, false); settingsReceive.SetChecked(latestState.ReceiveEnabled, false); } UpdateExplorerStatus(); folderRow.SetCaption(LocalTransferManagerC.Shared.OutputFolder); }

        ScrollPage incoming = pages[index];
        incoming.Visible = true;
        incoming.BringToFront();
        incoming.RequestLayout();
        if (old != null)
        {
            transition.BringToFront();
            Bitmap fresh = Ember.Snapshot(incoming);
            for (int i = 0; i < pages.Length; i++) if (i != index) pages[i].Visible = false;
            if (fresh != null) transition.Play(fresh, index > previous ? 1 : -1, null);
            else transition.Cancel();
        }
        else
        {
            for (int i = 0; i < pages.Length; i++) if (i != index) pages[i].Visible = false;
        }
    }

    private void OpenFileSender()
    {
        SwitchTab(1);
        RestoreFromTray();
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == (Keys.Control | Keys.D1)) { SwitchTab(0); return true; }
        if (keyData == (Keys.Control | Keys.D2)) { SwitchTab(1); return true; }
        if (keyData == (Keys.Control | Keys.D3)) { SwitchTab(2); return true; }
        if (keyData == (Keys.Control | Keys.O)) { ChooseTransferFiles(); return true; }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    // ----- clipboard -----
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        EmberNative.DarkChrome(Handle, true);
        if (!snapshotMode) { try { clipboardListener = EmberNative.AddClipboardFormatListener(Handle); } catch { clipboardListener = false; } }
    }

    protected override void OnHandleDestroyed(EventArgs e)
    {
        if (clipboardListener) { try { EmberNative.RemoveClipboardFormatListener(Handle); } catch { } clipboardListener = false; }
        base.OnHandleDestroyed(e);
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_CLIPBOARDUPDATE)
        {
            if (Visible && WindowState != FormWindowState.Minimized && !clipboardRefreshQueued)
            {
                clipboardRefreshQueued = true;
                Ember.Later(150, delegate { clipboardRefreshQueued = false; if (!IsDisposed && Visible) RefreshClipboardPreview(false); });
            }
        }
        base.WndProc(ref m);
    }

    protected override void OnActivated(EventArgs e)
    {
        base.OnActivated(e);
        if (selectedTab == 0) RefreshClipboardPreview(false);
    }

    private void RefreshClipboardPreview(bool force)
    {
        if (snapshotMode || clipboardCard == null || clipboardCard.IsDisposed || viewerOpen) return;
        if (!force)
        {
            uint sequence = 0;
            try { sequence = EmberNative.GetClipboardSequenceNumber(); } catch { }
            if (sequence != 0 && sequence == lastClipboardSequence) return;
        }
        ClipContent content;
        try { content = ClipboardReader.Read(); }
        catch { content = new ClipContent(); }
        lastClipboardSequence = content.Sequence;
        bool animate = Visible && selectedTab == 0 && pages[0].Visible;
        clipboardCard.SetContent(content, animate);
        if (content.ImagePending && !String.IsNullOrEmpty(content.ImagePath))
        {
            ClipContent target = content;
            ImageLoader.LoadAsync(clipboardCard, content.ImagePath, ClipboardReader.MaxImageEdge, delegate(Bitmap image) { clipboardCard.ImageLoaded(target, image); });
        }
    }

    // ----- drag & drop and file selection -----
    private void FileDragEnter(object sender, DragEventArgs e)
    {
        if (e.Data != null && e.Data.GetDataPresent(DataFormats.FileDrop)) { e.Effect = DragDropEffects.Copy; selectionCard.DragHot = true; }
        else e.Effect = DragDropEffects.None;
    }

    private void FileDragDrop(object sender, DragEventArgs e)
    {
        selectionCard.DragHot = false;
        string[] paths = e.Data == null ? null : e.Data.GetData(DataFormats.FileDrop) as string[];
        if (paths == null || paths.Length == 0) return;
        SwitchTab(1);
        AddPathsAsync(paths, false);
    }

    private void AddPathsAsync(IList<string> paths, bool announce)
    {
        List<string> input = new List<string>(paths);
        Task.Run(delegate
        {
            List<string> expanded = ShareInbox.Expand(input, 2000);
            UI(delegate
            {
                int added = AddTransferFiles(expanded);
                if (announce && added > 0) Notify("Added " + Ember.Plural(added, "file", "files"), ToastKind.Info);
                else if (expanded.Count == 0 && input.Count > 0) Notify("Nothing to send in that selection", ToastKind.Error);
            });
        });
    }

    private int AddTransferFiles(IEnumerable<string> paths)
    {
        int added = 0;
        foreach (string path in paths)
        {
            if (String.IsNullOrWhiteSpace(path) || !File.Exists(path)) continue;
            bool exists = false;
            foreach (string f in transferFiles) if (String.Equals(f, path, StringComparison.OrdinalIgnoreCase)) { exists = true; break; }
            if (exists) continue;
            if (transferFiles.Count >= 2000) break;
            transferFiles.Add(path); added++;
        }
        UpdateTransferFiles();
        if (added > 0) { LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); }
        return added;
    }

    private void ChooseOutputFolder()
    {
        using (FolderBrowserDialog picker = new FolderBrowserDialog())
        {
            picker.Description = "Choose ClipMesh receive folder"; picker.SelectedPath = LocalTransferManagerC.Shared.OutputFolder; picker.ShowNewFolderButton = true;
            if (picker.ShowDialog(this) != DialogResult.OK || String.IsNullOrWhiteSpace(picker.SelectedPath)) return;
            try { LocalTransferManagerC.Shared.OutputFolder = picker.SelectedPath; folderRow.SetCaption(LocalTransferManagerC.Shared.OutputFolder); Notify("Receive folder updated", ToastKind.Success); }
            catch (Exception ex) { ShowError(ex.Message); }
        }
    }

    private void OpenOutputFolder()
    {
        try
        {
            string folder = LocalTransferManagerC.Shared.OutputFolder;
            Directory.CreateDirectory(folder);
            Process.Start("explorer.exe", "\"" + folder + "\"");
        }
        catch (Exception ex) { ShowError(ex.Message); }
    }

    private static string FriendlyFolder()
    {
        string folder = LocalTransferManagerC.Shared.OutputFolder;
        try
        {
            string standard = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "ClipMesh");
            if (String.Equals(Path.GetFullPath(folder).TrimEnd('\\'), Path.GetFullPath(standard).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase)) return "Downloads\\ClipMesh";
        }
        catch { }
        return folder;
    }

    private void ChooseTransferFiles()
    {
        using (OpenFileDialog dialog = new OpenFileDialog())
        {
            dialog.Multiselect = true; dialog.Title = "Send with ClipMesh";
            if (dialog.ShowDialog(this) == DialogResult.OK) { if (selectedTab != 1) SwitchTab(1); AddTransferFiles(dialog.FileNames); }
        }
    }

    private void UpdateTransferFiles()
    {
        if (selectionCard == null) return;
        selectionCard.Sync(transferFiles, IsHandleCreated && Visible && selectedTab == 1);
    }

    // ----- devices -----
    private static string Ago(ulong lastSeenMs, ulong now)
    {
        ulong diff = now > lastSeenMs ? (now - lastSeenMs) / 1000UL : 0UL;
        if (diff < 60) return "just now";
        if (diff < 3600) return (diff / 60) + "m ago";
        if (diff < 86400) return (diff / 3600) + "h ago";
        return (diff / 86400) + "d ago";
    }

    private bool ListsAnimate(int tab) { return IsHandleCreated && Visible && selectedTab == tab && pages[tab].Visible && !transition.Active; }

    private void RenderPeers(List<PeerState> peers)
    {
        if (pairedList == null || pairedList.IsDisposed) return;
        ulong now = (ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        List<TransferDeviceC> nearby = LocalTransferManagerC.Shared.Nearby();
        pairedList.Sync<PeerState>(peers,
            delegate(PeerState p) { return p.Id; },
            delegate(PeerState p)
            {
                DeviceRow row = new DeviceRow();
                row.Remove = row.AddPart(new Part(PartKind.Icon, "", Glyph.Trash));
                row.Remove.Tip = "Remove"; row.Remove.GlyphSize = 15;
                row.Remove.IdleColor = Ember.TextFaint; row.Remove.HoverColor = Ember.Negative;
                DeviceRow captured = row;
                row.Remove.Click = delegate { PeerState current = captured.Tag2 as PeerState; if (current != null) RemovePeer(current); };
                return row;
            },
            delegate(ListRow r, PeerState p)
            {
                DeviceRow row = (DeviceRow)r;
                row.Tag2 = p;
                bool online = p.LastSeenMs > 0 && now >= p.LastSeenMs && now - p.LastSeenMs < OnlineWindowMs;
                string caption = online ? "Online" : (p.LastSeenMs == 0 ? "Paired" : "Last seen " + Ago(p.LastSeenMs, now));
                string type = null;
                foreach (TransferDeviceC d in nearby) if (String.Equals(d.Alias.Trim(), p.Name.Trim(), StringComparison.OrdinalIgnoreCase)) { type = d.Type; break; }
                row.SetData(p.Name, caption, online ? Ember.Positive : Color.Empty, online, Glyphs.LooksLikePhone(type, p.Name));
            },
            ListsAnimate(0));
        pages[0].RequestLayout();
        ArmOnlineTimer(peers, now);
    }

    private void RemovePeer(PeerState peer)
    {
        if (!ClipMeshDialogC.Show(this, "Remove " + peer.Name + "?", "It stops syncing with this PC until you pair again.", "Remove", "Cancel", true)) return;
        string removeId = peer.Id, removeName = peer.Name;
        Ember.Later(200, delegate
        {
            StopDaemon();
            try { ClipMeshRuntime.ForgetPeer(removeId); StartDaemon(); RefreshHome(); Notify("Removed " + removeName, ToastKind.Info); }
            catch (Exception ex) { try { StartDaemon(); } catch { } ShowError(ex.Message); }
        });
    }

    private void RefreshNearbyPairDevices()
    {
        if (nearbyList == null || nearbyList.IsDisposed) return;
        HashSet<string> pairedNames = new HashSet<string>((latestState == null ? new List<PeerState>() : latestState.Peers).ConvertAll(p => p.Name.Trim().ToLowerInvariant()));
        List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby().FindAll(d => !pairedNames.Contains(d.Alias.Trim().ToLowerInvariant()));
        nearbyList.Sync<TransferDeviceC>(devices,
            delegate(TransferDeviceC d) { return d.Fingerprint; },
            delegate(TransferDeviceC d)
            {
                DeviceRow row = new DeviceRow();
                row.ActionPart = row.AddPart(new Part(PartKind.Primary, "Pair", Glyph.None));
                row.ActionHeight = 28; row.ActionPart.FontSize = 12;
                DeviceRow captured = row;
                row.ActionPart.Click = delegate { TransferDeviceC current = captured.Tag2 as TransferDeviceC; if (current != null) StartNearbyPair(current); };
                return row;
            },
            delegate(ListRow r, TransferDeviceC d)
            {
                DeviceRow row = (DeviceRow)r;
                row.Tag2 = d;
                bool waiting = pairingKey != null && pairingKey == d.Fingerprint;
                row.ActionPart.Text = waiting ? "Waiting…" : "Pair";
                row.ActionPart.Enabled = pairingKey == null;
                row.SetData(d.Alias, DeviceCaption(d), Color.Empty, false, Glyphs.LooksLikePhone(d.Type, d.Alias));
                row.Invalidate();
            },
            ListsAnimate(0));
        pages[0].RequestLayout();
    }

    private static string DeviceCaption(TransferDeviceC d)
    {
        string model = (d.Model ?? "").Trim();
        if (model.Length > 0 && !String.Equals(model, d.Alias.Trim(), StringComparison.OrdinalIgnoreCase)) return model;
        return Glyphs.LooksLikePhone(d.Type, d.Alias) ? "Phone" : "Computer";
    }

    private void StartNearbyPair(TransferDeviceC device)
    {
        if (pairingKey != null) return;
        string credential; try { credential = ClipMeshRuntime.PairingLink(); } catch (Exception ex) { ShowError(ex.Message); return; }
        pairingKey = device.Fingerprint;
        RefreshNearbyPairDevices();
        Notify("Waiting for " + device.Alias + "…", ToastKind.Info);
        Task.Run(delegate
        {
            try
            {
                NearbyPairingManagerC.Shared.Pair(credential, device, delegate(string value) { if (!IsDisposed) BeginInvoke((Action)(delegate { ShowPairingCode(device.Alias, value); })); });
                if (!IsDisposed) BeginInvoke((Action)(delegate { ClosePairingCode(); pairingKey = null; Notify("Paired with " + device.Alias, ToastKind.Success); LocalTransferManagerC.Shared.DiscoverNow(); RefreshHome(); RefreshNearbyPairDevices(); }));
            }
            catch (Exception ex)
            {
                if (!IsDisposed) BeginInvoke((Action)(delegate { ClosePairingCode(); pairingKey = null; RefreshNearbyPairDevices(); ShowError(ex.Message); RefreshHome(); }));
            }
        });
    }

    private void ShowPairingCode(string device, string value)
    {
        ClosePairingCode();
        EmberDialog dialog = new EmberDialog();
        CodeBox code = new CodeBox(value);
        dialog.Build("Verification code", "Type this code on " + device + ".", code, Ember.S(440));
        pairingCodeWindow = dialog;
        dialog.FormClosed += delegate { if (pairingCodeWindow == dialog) pairingCodeWindow = null; };
        dialog.ShowModeless(this);
    }

    private void ClosePairingCode() { Form dialog = pairingCodeWindow; pairingCodeWindow = null; if (dialog != null && !dialog.IsDisposed) dialog.Close(); }

    private bool ApproveNearbyPair(string sender)
    {
        bool accepted = false;
        MethodInvoker work = delegate { RestoreFromTray(); accepted = ClipMeshDialogC.Show(this, "Pair with " + sender + "?", sender + " wants to pair with this PC for encrypted clipboard sync.", "Pair", "Decline", false); };
        if (InvokeRequired) Invoke(work); else work();
        return accepted;
    }

    private void PromptNearbyCode(string sender, Action<string> submit)
    {
        MethodInvoker work = delegate { string value = ClipMeshDialogC.Prompt(this, "Verify " + sender, "Type the six-digit code shown on " + sender + ".", "", "Verify", true); submit(value); };
        if (InvokeRequired) BeginInvoke(work); else work();
    }

    private bool AcceptNearbyCredential(string uri, string sender)
    {
        bool ok = false;
        MethodInvoker work = delegate
        {
            StopDaemon();
            try { ClipMeshRuntime.JoinSpace(uri, latestState == null ? Environment.MachineName : latestState.DeviceName); StartDaemon(); RefreshHome(); ok = true; Notify("Paired with " + sender, ToastKind.Success); }
            catch (Exception ex) { try { StartDaemon(); } catch { } ShowError(ex.Message); }
        };
        if (InvokeRequired) Invoke(work); else work();
        return ok;
    }

    private void RefreshTransferDevices()
    {
        if (transferDeviceList == null || transferDeviceList.IsDisposed) return;
        List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby();
        transferDeviceList.Sync<TransferDeviceC>(devices,
            delegate(TransferDeviceC d) { return d.Fingerprint; },
            delegate(TransferDeviceC d)
            {
                DeviceRow row = new DeviceRow();
                row.Star = row.AddPart(new Part(PartKind.Icon, "", Glyph.Star));
                row.Star.GlyphSize = 16; row.Star.IdleColor = Ember.TextFaint; row.Star.HoverColor = Ember.TextSoft;
                row.Star.Tip = "Trusted devices can send to you without asking";
                row.ActionPart = row.AddPart(new Part(PartKind.Primary, "Send", Glyph.None));
                row.ActionHeight = 30;
                DeviceRow captured = row;
                row.Star.Click = delegate
                {
                    TransferDeviceC current = captured.Tag2 as TransferDeviceC; if (current == null) return;
                    bool fav = !IsTrusted(current.Fingerprint);
                    try { LocalTransferManagerC.Shared.SetFavorite(current.Fingerprint, fav); } catch (Exception ex) { ShowError(ex.Message); return; }
                    RefreshTransferDevices();
                    Notify(fav ? current.Alias + " is trusted — its files save without asking" : current.Alias + " will ask before sending files", ToastKind.Info);
                };
                row.ActionPart.Click = delegate { TransferDeviceC current = captured.Tag2 as TransferDeviceC; if (current != null) SendTransfer(current); };
                return row;
            },
            delegate(ListRow r, TransferDeviceC d)
            {
                DeviceRow row = (DeviceRow)r;
                row.Tag2 = d;
                bool fav = IsTrusted(d.Fingerprint);
                row.Star.Toggled = fav;
                row.Star.Glyph = fav ? Glyph.StarFilled : Glyph.Star;
                row.Star.Tip = fav ? "Trusted — sends without asking. Click to stop trusting." : "Trusted devices can send to you without asking";
                row.Star.Enabled = sendingKey == null;
                row.ActionPart.Enabled = sendingKey == null;
                string caption;
                Color captionColor = Color.Empty;
                if (d.Fingerprint == sendingKey && sendingCaption != null) caption = sendingCaption;
                else if (row.Mode == RowMode.Sent) { caption = "Sent"; captionColor = Ember.Positive; }
                else caption = DeviceCaption(d) + (fav ? " · Trusted" : "");
                row.SetData(d.Alias, caption, captionColor, false, Glyphs.LooksLikePhone(d.Type, d.Alias));
                row.Invalidate();
            },
            ListsAnimate(1));
        pages[1].RequestLayout();
    }

    private DeviceRow SendRow(string fingerprint) { return transferDeviceList.Find(fingerprint) as DeviceRow; }

    private static int ParseSendIndex(string text)
    {
        System.Text.RegularExpressions.Match m = System.Text.RegularExpressions.Regex.Match(text ?? "", @"(\d+)\s*/\s*(\d+)\s*$");
        int value;
        return m.Success && Int32.TryParse(m.Groups[1].Value, out value) ? value : 0;
    }

    private void UpdateSendingCaption(string key)
    {
        if (sendingKey != key) return;
        string caption = sendingIndex <= 0 ? sendingCaption
            : "Sending " + (sendingCount > 1 ? sendingIndex + " of " + sendingCount + " · " : "") + sendingPercent + "%";
        sendingCaption = caption;
        DeviceRow r = SendRow(key);
        if (r != null) r.SetCaption(caption);
    }

    private bool IsTrusted(string fingerprint)
    {
        if (snapshotTrusted != null) return snapshotTrusted.Contains(fingerprint);
        try { return LocalTransferManagerC.Shared.IsFavorite(fingerprint); } catch { return false; }
    }

    private void SendTransfer(TransferDeviceC device)
    {
        if (sendingKey != null) return;
        if (transferFiles.Count == 0) { ChooseTransferFiles(); return; }
        List<string> files = new List<string>(transferFiles);
        int count = files.Count;
        string key = device.Fingerprint;
        sendingKey = key; sendingCaption = "Waiting for " + device.Alias + "…";
        sendingIndex = 0; sendingCount = count; sendingPercent = 0;
        DeviceRow started = SendRow(key);
        if (started != null) started.SetMode(RowMode.Sending);
        RefreshTransferDevices();
        Task.Run(delegate
        {
            try
            {
                LocalTransferManagerC.Shared.SendFiles(files, device,
                    delegate(string text) { UI(delegate { int index = ParseSendIndex(text); if (index > 0) sendingIndex = index; UpdateSendingCaption(key); }); },
                    delegate(int value) { UI(delegate { int transferProgress = Math.Max(0, Math.Min(1000, value)); sendingPercent = transferProgress / 10; DeviceRow r = SendRow(key); if (r != null) r.SetProgress(transferProgress); UpdateSendingCaption(key); CMTaskbarProgress.Set(Handle, value); }); });
                UI(delegate
                {
                    sendingKey = null; sendingCaption = null;
                    transferFiles.Clear(); UpdateTransferFiles();
                    CMTaskbarProgress.Clear(Handle);
                    DeviceRow r = SendRow(key);
                    if (r != null) { r.SetProgress(1000); r.SetMode(RowMode.Sent); }
                    RefreshTransferDevices();
                    Ember.Later(2400, delegate { DeviceRow done = SendRow(key); if (done != null && done.Mode == RowMode.Sent) { done.SetMode(RowMode.Idle); RefreshTransferDevices(); } });
                    string message = "Sent " + Ember.Plural(count, "file", "files") + " to " + device.Alias;
                    if (!Toast.Show(this, message, ToastKind.Success)) { balloonOpensFolder = false; tray.BalloonTipTitle = "Files sent"; tray.BalloonTipText = message; tray.ShowBalloonTip(2500); }
                });
            }
            catch (Exception ex)
            {
                UI(delegate
                {
                    sendingKey = null; sendingCaption = null;
                    CMTaskbarProgress.Clear(Handle);
                    DeviceRow r = SendRow(key);
                    if (r != null) r.SetMode(RowMode.Idle);
                    RefreshTransferDevices();
                    if (!Visible) { balloonOpensFolder = false; tray.BalloonTipTitle = "Transfer failed"; tray.BalloonTipText = ex.Message; tray.ShowBalloonTip(3500); }
                    ClipMeshDialogC.Show(this, "Couldn’t send", ex.Message, false);
                });
            }
        });
    }

    // ----- incoming -----
    private void ShowIncomingTransferProgress(string sender, string file, int value, bool complete)
    {
        if (IsDisposed) return;
        try
        {
            BeginInvoke((MethodInvoker)delegate
            {
                bool windowShown = Visible && WindowState != FormWindowState.Minimized;
                if (value < 0)
                {
                    CMTaskbarProgress.Clear(Handle); tray.Text = "ClipMesh"; lastIncomingBalloonPercent = -100;
                    transferStatus.Text = "Couldn’t receive " + file + " from " + sender;
                    transferStatus.Finish(false);
                    if (!windowShown) { balloonOpensFolder = false; tray.BalloonTipTitle = "Transfer failed"; tray.BalloonTipText = "Could not receive " + file + " from " + sender; tray.ShowBalloonTip(3000); }
                    else Notify("Couldn’t receive " + file, ToastKind.Error);
                    return;
                }
                int percent = Math.Max(0, Math.Min(100, value / 10));
                if (complete)
                {
                    CMTaskbarProgress.Clear(Handle); tray.Text = "ClipMesh"; lastIncomingBalloonPercent = -100;
                    transferStatus.Text = "Received from " + sender;
                    transferStatus.Finish(true);
                    string where = FriendlyFolder();
                    if (windowShown) Notify("Saved to " + where, ToastKind.Success);
                    else { balloonOpensFolder = true; tray.BalloonTipTitle = "Files received"; tray.BalloonTipText = "Saved from " + sender + " to " + where; tray.ShowBalloonTip(3000); }
                }
                else
                {
                    transferStatus.Receiving();
                    transferStatus.Progress = value;
                    CMTaskbarProgress.Set(Handle, value);
                    transferStatus.Text = "Receiving " + file + " from " + sender;
                    string tooltip = "ClipMesh - receiving " + percent + "%"; tray.Text = tooltip.Length > 63 ? tooltip.Substring(0, 63) : tooltip;
                    if (!windowShown && (lastIncomingBalloonPercent < 0 || percent - lastIncomingBalloonPercent >= 25))
                    {
                        lastIncomingBalloonPercent = percent; balloonOpensFolder = false;
                        tray.BalloonTipTitle = "Receiving from " + sender + " · " + percent + "%"; tray.BalloonTipText = file; tray.ShowBalloonTip(1500);
                    }
                }
            });
        }
        catch { }
    }

    private bool AskIncomingFiles(string sender, List<TransferFileMetaC> files)
    {
        bool accepted = false;
        MethodInvoker prompt = delegate
        {
            long total = 0; foreach (TransferFileMetaC f in files) total += Math.Max(0, f.Size);
            string what = files.Count == 1 ? files[0].Name : files.Count + " files";
            string message = sender + " wants to send you " + what + " (" + Ember.FormatBytes(total) + ")." + Environment.NewLine + "They'll be saved to " + FriendlyFolder() + ".";
            accepted = ClipMeshDialogC.Show(this, "Incoming files", message, "Accept", "Decline", false);
        };
        if (InvokeRequired) Invoke(prompt); else prompt();
        return accepted;
    }

    // ----- startup & daemon -----
    private void OnShown(object sender, EventArgs e)
    {
        pages[selectedTab].RequestLayout();
        if (snapshotMode) return;
        ShareInbox.Attach(delegate { UI(delegate { shareTimer.Stop(); shareTimer.Start(); }); });
        Task.Run(delegate
        {
            try
            {
                ClipMeshRuntime.PrepareFirstRun();
                UiState transferState = ClipMeshRuntime.GetUiState();
                ClipMeshShellIntegration.Register();
                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;
                LocalTransferManagerC.Shared.IncomingProgress = ShowIncomingTransferProgress;
                LocalTransferManagerC.Shared.Start(transferState.DeviceName);
                NearbyPairingManagerC.Shared.AliasProvider = delegate { return latestState == null ? transferState.DeviceName : latestState.DeviceName; };
                NearbyPairingManagerC.Shared.FingerprintProvider = delegate { return LocalTransferManagerC.Shared.Fingerprint; };
                NearbyPairingManagerC.Shared.DeviceIdProvider = delegate { return latestState == null ? ClipMeshRuntime.GetUiState().DeviceId : latestState.DeviceId; };
                NearbyPairingManagerC.Shared.PeerConsumer = delegate(string id, string name)
                {
                    bool ok = false;
                    MethodInvoker save = delegate { StopDaemon(); try { ClipMeshRuntime.SeedPeer(id, name); StartDaemon(); RefreshHome(); ok = true; Notify("Paired with " + name, ToastKind.Success); } catch (Exception ex) { try { StartDaemon(); } catch { } ShowError(ex.Message); } };
                    if (InvokeRequired) Invoke(save); else save();
                    return ok;
                };
                NearbyPairingManagerC.Shared.ApprovalPrompt = ApproveNearbyPair;
                NearbyPairingManagerC.Shared.CodePrompt = PromptNearbyCode;
                NearbyPairingManagerC.Shared.CredentialConsumer = AcceptNearbyCredential;
                NearbyPairingManagerC.Shared.Start();
                Invoke((MethodInvoker)delegate
                {
                    StartDaemon();
                    RefreshHome();
                    UpdateExplorerStatus();
                    startupDone = true;
                    UpdateObservers();
                });
            }
            catch (Exception ex)
            {
                Invoke((MethodInvoker)delegate { SetStatus(SyncStatus.Stopped); ShowError(ex.Message); });
            }
        });
    }

    private void ProcessShareInbox()
    {
        bool show;
        List<string> paths = ShareInbox.Drain(out show);
        if (paths.Count == 0) { if (show) RestoreFromTray(); return; }
        RestoreFromTray();
        SwitchTab(1);
        AddPathsAsync(paths, true);
    }

    private void SetStatus(SyncStatus status)
    {
        switch (status)
        {
            case SyncStatus.On: statusPill.SetStatus("Sync on", Ember.Positive, false); break;
            case SyncStatus.Recovering: statusPill.SetStatus("Recovering…", Ember.Accent, false); break;
            case SyncStatus.Stopped: statusPill.SetStatus("Sync stopped", Ember.Negative, true); break;
            default: statusPill.SetStatus("Starting…", Ember.Accent, false); break;
        }
        if (pages[0] != null) pages[0].RequestLayout();
    }

    private void RestartSync()
    {
        if (daemon != null) return;
        SetStatus(SyncStatus.Recovering);
        statusPill.Refresh();
        try { StartDaemon(); RefreshHome(); }
        catch (Exception ex) { SetStatus(SyncStatus.Stopped); ShowError(ex.Message); }
    }

    private void StartDaemon()
    {
        Process started = null;
        started = ClipMeshRuntime.StartDaemon(WriteLog, delegate(Process ended, int exitCode)
        {
            if (quitting || IsDisposed || daemon != ended) return;
            try
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    if (quitting || daemon != ended) return;
                    daemon = null;
                    SetStatus(SyncStatus.Stopped);
                    WriteLog("Background sync stopped (exit " + exitCode + ")");
                    RestoreFromTray();
                    Notify("Background sync stopped", ToastKind.Error);
                });
            }
            catch { }
        });
        daemon = started;
        SetStatus(SyncStatus.On);
    }

    private void StopDaemon()
    {
        Process process = daemon;
        daemon = null;
        if (process == null) return;
        try
        {
            if (!process.HasExited)
            {
                process.Kill();
                process.WaitForExit(3000);
            }
        }
        catch { }
        try { process.Dispose(); } catch { }
    }

    // Lets a closing dialog finish its exit animation before the (blocking) engine call runs.
    private void MutateLater(Action operation) { Ember.Later(200, delegate { if (!IsDisposed) MutateRuntime(operation); }); }

    private void MutateRuntime(Action operation)
    {
        SetStatus(SyncStatus.Recovering);
        try { statusPill.Refresh(); } catch { }
        StopDaemon();
        try
        {
            operation();
            StartDaemon();
            RefreshHome();
        }
        catch (Exception ex)
        {
            try { StartDaemon(); } catch { SetStatus(SyncStatus.Stopped); }
            ShowError(ex.Message);
        }
    }

    private void RefreshHome() { RefreshHome(false); }

    // quiet: periodic refreshes never pop errors (the status pill already reflects sync health).
    private void RefreshHome(bool quiet)
    {
        if (!IsHandleCreated || IsDisposed) return;
        int token = ++refreshToken;
        Task.Run(delegate
        {
            UiState state = null; Exception error = null;
            try { state = ClipMeshRuntime.GetUiState(); } catch (Exception ex) { error = ex; }
            UI(delegate
            {
                if (token != refreshToken) return;
                if (error != null) { if (!quiet) ShowError(error.Message); return; }
                ApplyState(state);
            });
        });
    }

    private void ApplyState(UiState state)
    {
        latestState = state;
        nameRow.SetCaption(state.DeviceName);
        deviceLine.Text = "This device · " + state.DeviceName;
        idRow.SetCaption(state.DeviceId);
        RenderPeers(state.Peers);
        bool animate = Visible && selectedTab == 2;
        if (!syncPending)
        {
            if (settingsSend.Checked != state.SendEnabled) settingsSend.SetChecked(state.SendEnabled, animate);
            if (settingsReceive.Checked != state.ReceiveEnabled) settingsReceive.SetChecked(state.ReceiveEnabled, animate);
        }
        if (selectedTab == 0) { RefreshNearbyPairDevices(); RefreshClipboardPreview(false); }
        if (daemon != null && !daemon.HasExited) SetStatus(SyncStatus.On);
    }

    // ----- settings actions -----
    private void ApplySyncToggles()
    {
        int token = ++syncToken;
        syncPending = true;
        Ember.Later(220, delegate
        {
            if (token != syncToken || IsDisposed) return;
            bool wantSend = settingsSend.Checked, wantReceive = settingsReceive.Checked;
            try { MutateRuntime(delegate { ClipMeshRuntime.SetSync(wantSend, wantReceive); }); }
            finally { if (token == syncToken) syncPending = false; }
        });
    }

    private void RenameDevice()
    {
        string current = latestState == null ? Environment.MachineName : latestState.DeviceName;
        string value = Prompt("Rename this device", "Your other devices will see this name.", current);
        if (value == null || String.IsNullOrWhiteSpace(value)) return;
        string name = value.Trim();
        MutateLater(delegate { ClipMeshRuntime.SetName(name); });
    }

    private void PairWithCode()
    {
        string code = ClipMeshDialogC.Prompt(this, "Pair with a code", "Paste the pairing code from your other device.", "", "Pair", true);
        if (code == null || String.IsNullOrWhiteSpace(code)) return;
        JoinDevice(code.Trim());
    }

    private void CopyPairingLink()
    {
        try
        {
            string link = ClipMeshRuntime.PairingLink();
            Clipboard.SetText(link);
            Notify("Pairing code copied", ToastKind.Success);
        }
        catch (Exception ex) { ShowError(ex.Message); }
    }

    private void JoinDevice(string uri)
    {
        if (String.IsNullOrWhiteSpace(uri)) { ShowError("Paste a ClipMesh pairing code first."); return; }
        if (!ConfirmReplacement("Join this private space?")) return;
        string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
        MutateLater(delegate { ClipMeshRuntime.JoinSpace(uri, name); });
    }

    private void CreateNewSpace()
    {
        if (!ConfirmReplacement("Create a new private space?")) return;
        string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
        MutateLater(delegate { ClipMeshRuntime.NewSpace(name); });
    }

    private void ResetPairing()
    {
        if (!ClipMeshDialogC.Show(this, "Reset all pairing?", "This creates a new device identity and private space and forgets every device.", "Reset", "Cancel", true)) return;
        string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
        MutateLater(delegate { ClipMeshRuntime.ResetIdentity(name); });
    }

    private bool ConfirmReplacement(string title)
    {
        return ClipMeshDialogC.Show(this, title, "This replaces this PC's current ClipMesh space and its list of devices.", true);
    }

    private void UpdateExplorerStatus()
    {
        bool ready = false;
        try { ready = ClipMeshShellIntegration.IsRegistered(); } catch { }
        explorerRow.SetCaption(ready ? "Send to and right-click menu are ready" : "Not set up — Repair adds Send to and right-click menu");
    }

    private void RepairExplorerIntegration()
    {
        Task.Run(delegate
        {
            ClipMeshShellIntegration.Register();
            UI(delegate
            {
                UpdateExplorerStatus();
                bool ready = false; try { ready = ClipMeshShellIntegration.IsRegistered(); } catch { }
                Notify(ready ? "Explorer integration repaired" : "Couldn’t update Explorer integration", ready ? ToastKind.Success : ToastKind.Error);
            });
        });
    }

    private void ShowError(string message)
    {
        RestoreFromTray();
        string text = (message ?? "").Trim();
        if (text.Length == 0) text = "Something went wrong.";
        if (text.Length <= 90 && text.IndexOf('\n') < 0 && Toast.Show(this, text, ToastKind.Error)) return;
        ClipMeshDialogC.Show(this, "Something went wrong", text, false);
    }

    private void Notify(string message, ToastKind kind)
    {
        if (Toast.Show(this, message, kind)) return;
        if (kind == ToastKind.Info) return;
        try { balloonOpensFolder = false; tray.BalloonTipTitle = "ClipMesh"; tray.BalloonTipText = message; tray.ShowBalloonTip(2500); } catch { }
    }

    private void UI(Action action)
    {
        if (IsDisposed || !IsHandleCreated) return;
        try { BeginInvoke(action); } catch { }
    }

    private void WriteLog(string line)
    {
        try
        {
            lock (logLock)
                File.AppendAllText(ClipMeshRuntime.LogPath, DateTime.Now.ToString("s") + " " + line + Environment.NewLine);
        }
        catch { }
    }

    // ----- --ui-snapshot support (fake data; no tray, daemon, network or clipboard access) -----
    internal void SeedSnapshot(string samples)
    {
        UiState state = new UiState();
        state.DeviceId = "6f1c2b7a-93d4-4e0b-a1c2-77d0c3e5f912"; state.DeviceName = "AYUS-DESKTOP"; state.SpaceId = "snapshot";
        ulong now = (ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        PeerState a = new PeerState(); a.Id = "peer-a"; a.Name = "Pixel 8 Pro"; a.LastSeenMs = now - 5000; state.Peers.Add(a);
        PeerState b = new PeerState(); b.Id = "peer-b"; b.Name = "MacBook Air"; b.LastSeenMs = now - 600000; state.Peers.Add(b);
        snapshotTrusted = new HashSet<string>(StringComparer.Ordinal); snapshotTrusted.Add("snap-pixel");
        ApplyState(state);
        SetStatus(SyncStatus.On);
        ClipContent clip = new ClipContent();
        clip.Kind = ClipKind.Text;
        clip.Text = "Meeting notes — Q4 planning. Ship ClipMesh with the new Ember UI across Android, macOS and Windows, then follow up on the transfer page empty state.";
        clipboardCard.SetContent(clip, false);
        foreach (string f in Directory.GetFiles(samples)) transferFiles.Add(f);
        UpdateTransferFiles();
        transferStatus.Text = "Receiving IMG_2041.jpg from Pixel 8 Pro";
        transferStatus.Receiving();
        transferStatus.Progress = 420;
        RefreshDeviceLists();
        sendingKey = "snap-pc"; sendingIndex = 2; sendingCount = 3; sendingPercent = 41; sendingCaption = "Sending 2 of 3 · 41%";
        RefreshTransferDevices();
        DeviceRow sending = SendRow("snap-pc");
        if (sending != null) { sending.SetMode(RowMode.Sending); sending.SetProgress(410); }
        for (int i = 0; i < 3; i++) pages[i].RequestLayout();
    }

    internal void ShowTabForSnapshot(int index) { SwitchTab(index); pages[index].RequestLayout(); }

    // Child windows are not limited by the screen's max track size, so the snapshot can be larger than the CI display.
    internal void LayoutForSnapshot(int width, int height)
    {
        sidebar.Dock = DockStyle.None;
        pageHost.Dock = DockStyle.None;
        sidebar.SetBounds(0, 0, sidebar.Width, height);
        pageHost.SetBounds(sidebar.Width, 0, width - sidebar.Width, height);
        for (int i = 0; i < 3; i++) pages[i].RequestLayout();
    }

    internal Bitmap CaptureClient()
    {
        Bitmap result = new Bitmap(Math.Max(1, pageHost.Right), Math.Max(1, Math.Max(sidebar.Height, pageHost.Height)), PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(result))
        {
            g.Clear(Ember.Bg);
            foreach (Control part in new Control[] { sidebar, pageHost })
            {
                Bitmap shot = Ember.Snapshot(part);
                if (shot == null) continue;
                g.DrawImage(shot, part.Left, part.Top, shot.Width, shot.Height);
                shot.Dispose();
            }
        }
        return result;
    }

    // ----- event-driven observers (attached only while the window is on screen) -----
    private bool observersAttached;

    private void UpdateObservers()
    {
        bool want = startupDone && !snapshotMode && !quitting && !IsDisposed && Visible && WindowState != FormWindowState.Minimized;
        if (want && !observersAttached) AttachObservers();
        else if (!want && observersAttached) DetachObservers();
    }

    private void AttachObservers()
    {
        observersAttached = true;
        if (!devicesSubscribed) { LocalTransferManagerC.Shared.DevicesChanged += OnDevicesChanged; devicesSubscribed = true; }
        if (configWatcher == null)
        {
            string dir = ClipMeshRuntime.ConfigDirectory;
            if (!String.IsNullOrEmpty(dir) && Directory.Exists(dir))
            {
                try
                {
                    FileSystemWatcher watcher = new FileSystemWatcher(dir, "*.json");
                    watcher.NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.FileName | NotifyFilters.Size;
                    watcher.IncludeSubdirectories = false;
                    watcher.SynchronizingObject = this;
                    watcher.Changed += OnConfigFileEvent;
                    watcher.Created += OnConfigFileEvent;
                    watcher.Deleted += OnConfigFileEvent;
                    watcher.Renamed += delegate(object sender, RenamedEventArgs e) { OnConfigFileEvent(sender, e); };
                    watcher.EnableRaisingEvents = true;
                    configWatcher = watcher;
                }
                catch { configWatcher = null; }
            }
        }
        // Catch up once on what changed while we were hidden, then one on-demand probe.
        RefreshDeviceLists();
        LoadPeersFile();
        ProbePeers();
    }

    // A peer reached by traffic or an on-demand probe within this window shows as Online.
    private const ulong OnlineWindowMs = 300000UL;
    private int probeInFlight;

    // On-demand presence: one `probe-peers` run (TCP connect to each paired peer). The
    // daemon refreshes peers.json and the config watcher re-renders. No heartbeat.
    private void ProbePeers()
    {
        if (snapshotMode || Interlocked.CompareExchange(ref probeInFlight, 1, 0) != 0) return;
        ThreadPool.QueueUserWorkItem(delegate
        {
            try { ClipMeshRuntime.Run("probe-peers"); } catch { }
            Interlocked.Exchange(ref probeInFlight, 0);
        });
    }

    private void DetachObservers()
    {
        observersAttached = false;
        if (devicesSubscribed) { LocalTransferManagerC.Shared.DevicesChanged -= OnDevicesChanged; devicesSubscribed = false; }
        if (configWatcher != null)
        {
            try { configWatcher.EnableRaisingEvents = false; configWatcher.Dispose(); } catch { }
            configWatcher = null;
        }
        peersDebounce.Stop(); configDebounce.Stop(); onlineTimer.Stop();
    }

    // Called on a thread-pool thread by the transfer engine (already coalesced ~100ms).
    private void OnDevicesChanged()
    {
        UI(delegate { if (observersAttached) RefreshDeviceLists(); });
    }

    private void RefreshDeviceLists()
    {
        RefreshNearbyPairDevices();
        RefreshTransferDevices();
        if (latestState != null) RenderPeers(latestState.Peers);
    }

    private void OnConfigFileEvent(object sender, FileSystemEventArgs e)
    {
        if (!observersAttached) return;
        string name = e.Name ?? "";
        if (name.Equals("peers.json", StringComparison.OrdinalIgnoreCase)) Restart(peersDebounce);
        else if (name.Equals("config.json", StringComparison.OrdinalIgnoreCase)) Restart(configDebounce);
    }

    // Reads peers.json directly (same data `ui-state` prints) instead of spawning the engine.
    private void LoadPeersFile()
    {
        if (latestState == null) return;
        string dir = ClipMeshRuntime.ConfigDirectory;
        if (String.IsNullOrEmpty(dir)) return;
        string path = Path.Combine(dir, "peers.json");
        string text = null;
        for (int attempt = 0; attempt < 2 && text == null; attempt++)
        {
            try
            {
                if (!File.Exists(path)) return;
                using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (StreamReader reader = new StreamReader(stream, Encoding.UTF8)) text = reader.ReadToEnd();
            }
            catch (IOException) { Thread.Sleep(30); }
            catch { return; }
        }
        if (text == null) return;
        List<PeerState> peers = new List<PeerState>();
        try
        {
            System.Web.Script.Serialization.JavaScriptSerializer json = new System.Web.Script.Serialization.JavaScriptSerializer();
            Dictionary<string, object> root = json.DeserializeObject(text) as Dictionary<string, object>;
            if (root == null) return;
            object schema, space, list;
            if (!root.TryGetValue("schema", out schema) || Convert.ToInt32(schema) != 1) return;
            bool sameSpace = root.TryGetValue("space_id", out space) && String.Equals(Convert.ToString(space), latestState.SpaceId, StringComparison.OrdinalIgnoreCase);
            if (sameSpace && root.TryGetValue("peers", out list))
            {
                System.Collections.IEnumerable items = list as System.Collections.IEnumerable;
                if (items != null)
                {
                    foreach (object item in items)
                    {
                        Dictionary<string, object> peer = item as Dictionary<string, object>;
                        if (peer == null) continue;
                        object id, name, seen;
                        if (!peer.TryGetValue("device_id", out id)) continue;
                        PeerState state = new PeerState();
                        state.Id = Convert.ToString(id);
                        state.Name = peer.TryGetValue("name", out name) ? (Convert.ToString(name) ?? "").Trim() : "";
                        if (state.Name.Length == 0) state.Name = "Device";
                        ulong lastSeen = 0;
                        if (peer.TryGetValue("last_seen_ms", out seen) && seen != null) { try { lastSeen = Convert.ToUInt64(seen); } catch { lastSeen = 0; } }
                        state.LastSeenMs = lastSeen;
                        peers.Add(state);
                    }
                }
            }
        }
        catch { return; }
        latestState.Peers.Clear();
        latestState.Peers.AddRange(peers);
        RenderPeers(latestState.Peers);
        RefreshNearbyPairDevices();
    }

    // One one-shot timer for the soonest Online -> "Last seen" transition.
    private void ArmOnlineTimer(List<PeerState> peers, ulong now)
    {
        onlineTimer.Stop();
        if (snapshotMode || !observersAttached) return;
        ulong soonest = UInt64.MaxValue;
        foreach (PeerState p in peers)
        {
            if (p.LastSeenMs == 0 || now < p.LastSeenMs || now - p.LastSeenMs >= OnlineWindowMs) continue;
            ulong remaining = OnlineWindowMs - (now - p.LastSeenMs);
            if (remaining < soonest) soonest = remaining;
        }
        if (soonest == UInt64.MaxValue) return;
        onlineTimer.Interval = (int)Math.Min(OnlineWindowMs + 500UL, Math.Max(500UL, soonest + 500UL));
        onlineTimer.Start();
    }

    // ----- window lifecycle -----
    private void OnFormClosing(object sender, FormClosingEventArgs e)
    {
        if (quitting) return;
        if (e.CloseReason == CloseReason.WindowsShutDown || e.CloseReason == CloseReason.TaskManagerClosing) return;
        e.Cancel = true;
        HideToTray();
    }

    private void HideToTray()
    {
        LocalTransferManagerC.Shared.SetUiVisible(false);
        Hide();
        ShowInTaskbar = false;
        UpdateObservers();
    }

    private void RestoreFromTray()
    {
        if (IsDisposed) return;
        ShowInTaskbar = true;
        if (!Visible) Show();
        LocalTransferManagerC.Shared.SetUiVisible(true);
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        BringToFront();
        Activate();
        try { EmberNative.SetForegroundWindow(Handle); } catch { }
        UpdateObservers();
    }

    private void QuitCompletely()
    {
        quitting = true;
        tray.Visible = false;
        NearbyPairingManagerC.Shared.Stop();
        LocalTransferManagerC.Shared.Stop();
        StopDaemon();
        Application.Exit();
    }

    private string Prompt(string title, string hint, string current)
    {
        return ClipMeshDialogC.Prompt(this, title, hint, current, "Save", false);
    }

    private static Icon CreateTrayIcon()
    {
        Bitmap bitmap = new Bitmap(32, 32, PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(bitmap))
        {
            g.Clear(Color.Transparent);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            Point[] top = new Point[] { new Point(4, 10), new Point(25, 10), new Point(19, 4), new Point(25, 10), new Point(19, 16) };
            Point[] bottom = new Point[] { new Point(28, 22), new Point(7, 22), new Point(13, 16), new Point(7, 22), new Point(13, 28) };
            using (Pen outline = new Pen(Color.Black, 5.0f))
            using (Pen inside = new Pen(Color.White, 2.5f))
            {
                outline.StartCap = LineCap.Round; outline.EndCap = LineCap.Round; outline.LineJoin = LineJoin.Round;
                inside.StartCap = LineCap.Round; inside.EndCap = LineCap.Round; inside.LineJoin = LineJoin.Round;
                g.DrawLines(outline, top); g.DrawLines(outline, bottom);
                g.DrawLines(inside, top); g.DrawLines(inside, bottom);
            }
        }
        IntPtr handle = bitmap.GetHicon();
        try
        {
            using (Icon temp = Icon.FromHandle(handle)) return (Icon)temp.Clone();
        }
        finally
        {
            DestroyIcon(handle);
            bitmap.Dispose();
        }
    }

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern bool DestroyIcon(IntPtr handle);

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            tray.Visible = false;
            tray.Dispose();
            trayIcon.Dispose();
            DetachObservers();
            peersDebounce.Dispose();
            configDebounce.Dispose();
            onlineTimer.Dispose();
            shareTimer.Dispose();
        }
        base.Dispose(disposing);
    }
}

// ---------------------------------------------------------------------------
// --ui-snapshot <dir>: renders the real UI with fake data at 100% and 150% scale (CI visual check).
// ---------------------------------------------------------------------------
internal static class UiSnapshot
{
    private static void Pump(int ms)
    {
        Stopwatch watch = Stopwatch.StartNew();
        while (watch.ElapsedMilliseconds < ms) { Application.DoEvents(); Thread.Sleep(10); }
    }

    private static void Save(Bitmap bitmap, string path)
    {
        if (bitmap == null) throw new InvalidOperationException("Nothing rendered for " + path);
        bitmap.Save(path, ImageFormat.Png);
        bitmap.Dispose();
        Console.WriteLine("wrote " + path);
    }

    private static string Samples()
    {
        string dir = Path.Combine(Path.GetTempPath(), "clipmesh-ui-snapshot");
        Directory.CreateDirectory(dir);
        foreach (string old in Directory.GetFiles(dir)) { try { File.Delete(old); } catch { } }
        File.WriteAllBytes(Path.Combine(dir, "Quarterly report.pdf"), new byte[245760]);
        File.WriteAllText(Path.Combine(dir, "notes.txt"), "ClipMesh snapshot sample");
        using (Bitmap photo = new Bitmap(1200, 800))
        using (Graphics g = Graphics.FromImage(photo))
        using (LinearGradientBrush sky = new LinearGradientBrush(new Rectangle(0, 0, 1200, 800), Color.FromArgb(0xF2, 0x9A, 0x4B), Color.FromArgb(0x3B, 0x2A, 0x5C), 70f))
        {
            g.FillRectangle(sky, 0, 0, 1200, 800);
            using (SolidBrush hill = new SolidBrush(Color.FromArgb(0x1E, 0x24, 0x33))) g.FillEllipse(hill, -200, 520, 1600, 700);
            photo.Save(Path.Combine(dir, "Trip photo.jpg"), ImageFormat.Jpeg);
        }
        return dir;
    }

    public static int Run(string output)
    {
        try
        {
            // Fail fast (exit code) instead of showing an exception dialog that would hang CI.
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Ember.Init();
            Anim.ReduceMotion = true;
            output = Path.GetFullPath(String.IsNullOrWhiteSpace(output) ? "snapshots" : output);
            Directory.CreateDirectory(output);
            string samples = Samples();
            List<TransferDeviceC> devices = new List<TransferDeviceC>();
            TransferDeviceC pixel = new TransferDeviceC(); pixel.Alias = "Pixel 8 Pro"; pixel.Fingerprint = "snap-pixel"; pixel.Model = "Pixel 8 Pro"; pixel.Type = "mobile"; devices.Add(pixel);
            TransferDeviceC pc = new TransferDeviceC(); pc.Alias = "Living room PC"; pc.Fingerprint = "snap-pc"; pc.Model = "DESKTOP-7Q2"; pc.Type = "desktop"; devices.Add(pc);
            TransferDeviceC tab = new TransferDeviceC(); tab.Alias = "Galaxy Tab"; tab.Fingerprint = "snap-tab"; tab.Model = "SM-X710"; tab.Type = "mobile"; devices.Add(tab);
            LocalTransferManagerC.Shared.SeedSnapshotDevices(devices);
            float[] scales = new float[] { 1f, 1.5f };
            foreach (float scale in scales)
            {
                Ember.SetScale(scale);
                string suffix = "-" + (int)Math.Round(scale * 100);
                using (ClipMeshForm form = new ClipMeshForm(true))
                {
                    form.ShowInTaskbar = false;
                    form.StartPosition = FormStartPosition.Manual;
                    form.Location = new Point(-20000, -20000);
                    form.Show();
                    form.LayoutForSnapshot(Ember.S(1000), Ember.S(700));
                    Pump(200);
                    form.SeedSnapshot(samples);
                    Pump(600);
                    for (int i = 0; i < 3; i++)
                    {
                        form.ShowTabForSnapshot(i);
                        Pump(250);
                        Save(form.CaptureClient(), Path.Combine(output, "page" + i + suffix + ".png"));
                    }
                    using (EmberDialog dialog = new EmberDialog())
                    {
                        dialog.AddButton("Cancel", PartKind.Secondary, DialogResult.Cancel);
                        dialog.AddButton("Remove", PartKind.Destructive, DialogResult.OK);
                        dialog.Build("Remove Pixel 8 Pro?", "It stops syncing with this PC until you pair again.", null, Ember.S(440));
                        dialog.StartPosition = FormStartPosition.Manual;
                        dialog.Location = new Point(-20000, -20000);
                        dialog.Show();
                        Pump(250);
                        Save(Ember.Snapshot(dialog), Path.Combine(output, "dialog" + suffix + ".png"));
                        dialog.Hide();
                    }
                    using (Bitmap toast = Toast.Render("Sent 3 files to Pixel 8 Pro", ToastKind.Success))
                    {
                        Bitmap canvas = new Bitmap(toast.Width + Ember.S(48), toast.Height + Ember.S(48));
                        using (Graphics g = Graphics.FromImage(canvas)) { g.Clear(Ember.Bg); g.DrawImage(toast, Ember.S(24), Ember.S(24), toast.Width, toast.Height); }
                        Save(canvas, Path.Combine(output, "toast" + suffix + ".png"));
                    }
                    form.Hide();
                }
            }
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ui-snapshot failed: " + ex);
            return 1;
        }
    }
}

// ---------------------------------------------------------------------------
// Explorer "Send with ClipMesh" / Send to: forwards paths to the running instance.
// ---------------------------------------------------------------------------
internal static class ShareInbox
{
    private const string Header = "CLIPMESH-SHARE-1";
    private static readonly object gate = new object();
    private static readonly List<string> queue = new List<string>();
    private static bool showRequested;
    private static Action handler;

    public static string PipeName
    {
        get
        {
            string id;
            try { id = System.Security.Principal.WindowsIdentity.GetCurrent().User.Value; }
            catch { id = Environment.UserDomainName + "." + Environment.UserName; }
            return "ClipMesh.Share." + id;
        }
    }

    public static void StartServer()
    {
        Thread thread = new Thread(ServerLoop);
        thread.IsBackground = true;
        thread.Name = "ClipMesh share inbox";
        thread.Start();
    }

    private static void ServerLoop()
    {
        string name = PipeName;
        int failures = 0;
        while (true)
        {
            try
            {
                using (NamedPipeServerStream server = new NamedPipeServerStream(name, PipeDirection.In, NamedPipeServerStream.MaxAllowedServerInstances, PipeTransmissionMode.Byte, PipeOptions.None))
                {
                    server.WaitForConnection();
                    List<string> lines = new List<string>();
                    using (StreamReader reader = new StreamReader(server, new UTF8Encoding(false)))
                    {
                        string line;
                        while ((line = reader.ReadLine()) != null && lines.Count < 50000) lines.Add(line);
                    }
                    Deliver(lines);
                }
                failures = 0;
            }
            catch
            {
                if (++failures > 50) return;
                Thread.Sleep(250);
            }
        }
    }

    private static void Deliver(List<string> lines)
    {
        if (lines.Count == 0 || lines[0] != Header) return;
        List<string> paths = new List<string>();
        bool show = false;
        for (int i = 1; i < lines.Count; i++)
        {
            string line = lines[i];
            if (line == "SHOW") show = true;
            else if (line.StartsWith("PATH\t", StringComparison.Ordinal)) { string p = line.Substring(5).Trim(); if (p.Length > 0) paths.Add(p); }
        }
        Enqueue(paths, show);
    }

    public static void Enqueue(IEnumerable<string> paths, bool show)
    {
        Action h;
        lock (gate)
        {
            foreach (string p in paths) queue.Add(p);
            if (show) showRequested = true;
            h = handler;
        }
        if (h != null) { try { h(); } catch { } }
    }

    public static void Attach(Action onArrival)
    {
        bool pending;
        lock (gate) { handler = onArrival; pending = queue.Count > 0 || showRequested; }
        if (pending) onArrival();
    }

    public static List<string> Drain(out bool show)
    {
        lock (gate)
        {
            List<string> result = new List<string>(queue);
            queue.Clear();
            show = showRequested;
            showRequested = false;
            return result;
        }
    }

    public static bool Forward(IList<string> paths, int timeoutSeconds)
    {
        try { EmberNative.AllowSetForegroundWindow(-1); } catch { }
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (true)
        {
            try
            {
                using (NamedPipeClientStream client = new NamedPipeClientStream(".", PipeName, PipeDirection.Out))
                {
                    client.Connect(1500);
                    StreamWriter writer = new StreamWriter(client, new UTF8Encoding(false));
                    writer.WriteLine(Header);
                    writer.WriteLine("SHOW");
                    foreach (string path in paths)
                    {
                        string full = path;
                        try { full = Path.GetFullPath(path); } catch { }
                        writer.WriteLine("PATH\t" + full);
                    }
                    writer.Flush();
                    try { client.WaitForPipeDrain(); } catch { }
                }
                return true;
            }
            catch
            {
                if (DateTime.UtcNow > deadline) return false;
                Thread.Sleep(250);
            }
        }
    }

    // Expands folders into their regular files (recursively, skipping hidden/system entries), capped.
    public static List<string> Expand(IEnumerable<string> paths, int cap)
    {
        List<string> result = new List<string>();
        HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string raw in paths)
        {
            if (result.Count >= cap) break;
            string path = raw;
            try { path = Path.GetFullPath(raw.Trim().Trim('"')); } catch { continue; }
            try
            {
                if (File.Exists(path)) { if (seen.Add(path)) result.Add(path); continue; }
                if (!Directory.Exists(path)) continue;
                Stack<string> pending = new Stack<string>();
                pending.Push(path);
                while (pending.Count > 0 && result.Count < cap)
                {
                    string dir = pending.Pop();
                    string[] files = new string[0], dirs = new string[0];
                    try { files = Directory.GetFiles(dir); } catch { }
                    Array.Sort(files, StringComparer.OrdinalIgnoreCase);
                    foreach (string file in files)
                    {
                        if (result.Count >= cap) break;
                        try
                        {
                            FileAttributes a = File.GetAttributes(file);
                            if ((a & (FileAttributes.Hidden | FileAttributes.System | FileAttributes.Directory)) != 0) continue;
                        }
                        catch { continue; }
                        if (seen.Add(file)) result.Add(file);
                    }
                    try { dirs = Directory.GetDirectories(dir); } catch { }
                    Array.Sort(dirs, StringComparer.OrdinalIgnoreCase);
                    for (int i = dirs.Length - 1; i >= 0; i--)
                    {
                        try
                        {
                            FileAttributes a = File.GetAttributes(dirs[i]);
                            if ((a & (FileAttributes.Hidden | FileAttributes.System | FileAttributes.ReparsePoint)) != 0) continue;
                        }
                        catch { continue; }
                        pending.Push(dirs[i]);
                    }
                }
            }
            catch { }
        }
        return result;
    }
}

internal static class Program
{
    private static Mutex singleInstance;

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length >= 1 && args[0] == "--ui-snapshot") return UiSnapshot.Run(args.Length >= 2 ? args[1] : "snapshots");
        bool share = args.Length >= 1 && args[0] == "--share";
        bool smoke = Array.IndexOf(args, "--smoke-test") >= 0;
        List<string> sharePaths = new List<string>();
        if (share) for (int i = 1; i < args.Length; i++) if (!String.IsNullOrWhiteSpace(args[i])) sharePaths.Add(args[i]);
        if (!smoke) { try { EmberNative.SetProcessDPIAware(); } catch { } }

        bool created;
        singleInstance = new Mutex(true, "Local\\ClipMesh.Desktop", out created);
        if (!created)
        {
            singleInstance.Dispose();
            singleInstance = null;
            if (smoke) return 0;
            // Another ClipMesh is running: hand it the shared files (or just bring it forward).
            bool forwarded = ShareInbox.Forward(sharePaths, share ? 12 : 3);
            if (!forwarded && share)
            {
                Application.EnableVisualStyles();
                ClipMeshDialogC.Show(null, "ClipMesh didn’t respond", "ClipMesh is running but couldn’t take the files. Try again in a moment.", false);
                return 1;
            }
            return 0;
        }
        try
        {
            if (smoke)
            {
                ClipMeshRuntime.PrepareFirstRun();
                ClipMeshRuntime.GetUiState();
                Console.WriteLine("ClipMesh native Windows first-run smoke test passed");
                return 0;
            }
            ShareInbox.StartServer();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Ember.Init();
            if (share) ShareInbox.Enqueue(sharePaths, true);
            Application.Run(new ClipMeshForm());
            return 0;
        }
        catch (Exception ex)
        {
            ClipMeshDialogC.Show(null, "ClipMesh", ex.Message, false);
            return 1;
        }
        finally
        {
            if (singleInstance != null)
            {
                singleInstance.ReleaseMutex();
                singleInstance.Dispose();
            }
        }
    }
}
