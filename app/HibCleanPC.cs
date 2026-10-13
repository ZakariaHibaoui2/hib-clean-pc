// Hib Clean PC: a WebView2 window whose interface (ui/) asks this host to run
// small PowerShell scripts (scripts/) and returns their JSON output.
//
// Bridge protocol (window.chrome.webview.postMessage):
//   page -> host  { id, cmd, args, admin }
//   host -> page  { id, ok, data | error }
// `cmd` is either a built-in host command (window, pdf, open) or the name of a
// bundled script. Only bundled scripts can run; arguments travel as base64 JSON,
// never on the command line as text, so nothing from the page is ever parsed by
// the shell. Scripts marked `admin` run through one UAC prompt per action.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Hib Clean PC")]
[assembly: AssemblyProduct("Hib Clean PC")]
[assembly: AssemblyCompany("Zakaria Hibaoui")]
[assembly: AssemblyCopyright("GPL-3.0")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]
[assembly: AssemblyInformationalVersion("1.1.0")]

namespace HibCleanPC
{
    static class Program
    {
        public const string Version = "1.1.0";
        public const string Host = "app.hibclean";
        public static readonly string DataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Hib Clean PC");

        // The manifest (tools/build.py) makes the app per-monitor DPI aware (V2), so text and
        // the WebView stay sharp at any scaling and when the window moves between screens.
        // This call only matters if the manifest was lost; it fails harmlessly otherwise.
        [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr value);

        [STAThread]
        static void Main(string[] args)
        {
            AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
            {
                string name = new AssemblyName(e.Name).Name + ".dll";
                using (var res = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
                {
                    if (res == null) return null;
                    var bytes = new byte[res.Length];
                    res.Read(bytes, 0, bytes.Length);
                    return Assembly.Load(bytes);
                }
            };
            try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch { } // PER_MONITOR_AWARE_V2, Windows 10 1703+
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Run(args);
        }

        // Kept separate so the WebView2 assemblies resolve after AssemblyResolve is set.
        static void Run(string[] args)
        {
            try
            {
                Unpack();
            }
            catch (Exception ex)
            {
                MessageBox.Show("Hib Clean PC couldn't prepare its files: " + ex.Message, "Hib Clean PC",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            Application.Run(new MainForm(args));
        }

        static string root;
        public static string Res(string sub) { return Path.Combine(root, sub); }
        // x86, x64 or arm64: the WebView2 loader this process can load (see Arch.cs).
        public static readonly string Arch = HibCleanPC.Arch.Current();
        public static string LoaderDir { get { return Res(Path.Combine("runtime", Arch)); } }

        // Extracts the interface, the scripts and the WebView2 loader next to each other,
        // into a folder of their own per build. A copy of the app that is still running keeps
        // its files open; a new build then never has to overwrite them.
        static void Unpack()
        {
            var asm = Assembly.GetExecutingAssembly();
            string build = asm.GetManifestResourceNames().Contains("build.txt") ? ReadRes("build.txt").Trim() : Version;
            string name = Regex.Replace(build, "[^A-Za-z0-9.]", "");
            if (name.Length > 16) name = name.Substring(0, 16);
            string parent = Path.Combine(DataDir, "app");
            root = Path.Combine(parent, name);
            if (File.Exists(Path.Combine(root, ".ready"))) { Tidy(parent); return; }

            // Built in a temporary folder and moved into place at the end, so a half-written
            // copy is never used and two copies starting together can't clash.
            string temp = Path.Combine(parent, "tmp-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temp);
            try
            {
                foreach (var pair in new[] { "ui.zip|ui", "scripts.zip|scripts" })
                {
                    var p = pair.Split('|');
                    using (var s = asm.GetManifestResourceStream(p[0]))
                    using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
                    {
                        string dest = Path.Combine(temp, p[1]);
                        foreach (var entry in zip.Entries)
                        {
                            string full = Path.GetFullPath(Path.Combine(dest, entry.FullName));
                            if (!full.StartsWith(Path.GetFullPath(dest) + Path.DirectorySeparatorChar)) continue;
                            if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(full); continue; }
                            Directory.CreateDirectory(Path.GetDirectoryName(full));
                            entry.ExtractToFile(full, true);
                        }
                    }
                }
                // Every architecture's loader is inside the exe; each gets its own folder, so the
                // same unpacked build works whichever way Windows runs the app (x64, ARM64, x86).
                foreach (string arch in new[] { "x86", "x64", "arm64" })
                {
                    using (var s = asm.GetManifestResourceStream(HibCleanPC.Arch.Resource(arch)))
                    {
                        if (s == null) continue;
                        string runtime = Path.Combine(temp, "runtime", arch);
                        Directory.CreateDirectory(runtime);
                        using (var f = File.Create(Path.Combine(runtime, "WebView2Loader.dll"))) s.CopyTo(f);
                    }
                }
                File.WriteAllText(Path.Combine(temp, ".ready"), build);
                if (Directory.Exists(root)) TryDelete(root);   // an unfinished older attempt
                if (!Directory.Exists(root)) Directory.Move(temp, root);
            }
            finally
            {
                if (Directory.Exists(temp)) TryDelete(temp);
            }
            if (!File.Exists(Path.Combine(root, ".ready"))) throw new IOException("the app folder could not be prepared in " + parent);
            Tidy(parent);
        }

        // Removes other builds' folders (and the pre-1.0.1 layout); skips any still in use.
        static void Tidy(string parent)
        {
            foreach (var dir in Directory.GetDirectories(parent))
            {
                if (string.Equals(dir, root, StringComparison.OrdinalIgnoreCase)) continue;
                // Another copy may be unpacking into its temporary folder right now.
                if (Path.GetFileName(dir).StartsWith("tmp-") && Directory.GetCreationTimeUtc(dir) > DateTime.UtcNow.AddHours(-1)) continue;
                TryDelete(dir);
            }
            string legacy = Path.Combine(DataDir, Version);
            if (Directory.Exists(legacy)) TryDelete(legacy);
        }

        static void TryDelete(string dir)
        {
            try { Directory.Delete(dir, true); } catch { }
        }

        public static string ReadRes(string name)
        {
            using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
            using (var r = new StreamReader(s, Encoding.UTF8)) return r.ReadToEnd();
        }
    }

    class MainForm : Form
    {
        readonly WebView2 web = new WebView2();
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        readonly string startPage;
        FormWindowState beforeFull;
        FormBorderStyle beforeBorder;
        bool full;

        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        public MainForm(string[] args)
        {
            Text = "Hib Clean PC";
            BackColor = Color.FromArgb(14, 36, 39);
            PlaceWindow();
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            // ?page=... lets tests open a specific screen.
            string page = args.FirstOrDefault(a => a.StartsWith("--page="));
            startPage = "https://" + Program.Host + "/index.html" + (page != null ? "#" + page.Substring(7) : "");
            web.Dock = DockStyle.Fill;
            web.DefaultBackgroundColor = BackColor;
            Controls.Add(web);
            Load += async (s, e) => await Start();
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            int on = 1;
            // Dark title bar: attribute 20 on Windows 10 20H1 and later, 19 before that.
            try { if (DwmSetWindowAttribute(Handle, 20, ref on, 4) != 0) DwmSetWindowAttribute(Handle, 19, ref on, 4); } catch { }
        }

        // ---------- Window size on any screen ----------
        // Sizes are in logical pixels (100% scaling), scaled for the screen's DPI, because a
        // per-monitor aware window is measured in physical pixels.
        static readonly Size Preferred = new Size(1240, 820);
        static readonly Size Smallest = new Size(800, 560);
        const int WM_DPICHANGED = 0x02E0;

        [DllImport("user32.dll")] static extern IntPtr MonitorFromPoint(Point pt, uint flags);
        [DllImport("shcore.dll")] static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint dpiX, out uint dpiY);
        [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr hwnd);
        [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
        [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }

        static int DpiAt(Point p)
        {
            try
            {
                uint x, y;
                if (GetDpiForMonitor(MonitorFromPoint(p, 2), 0, out x, out y) == 0 && x > 0) return (int)x;
            }
            catch { }
            using (var g = Graphics.FromHwnd(IntPtr.Zero)) return (int)g.DpiX;
        }

        static Size Scale(Size s, int dpi) { return new Size(s.Width * dpi / 96, s.Height * dpi / 96); }

        // Never larger than the screen's work area, even at 1366x768 with 150% scaling.
        static Size Fit(Size s, Rectangle area) { return new Size(Math.Min(s.Width, area.Width), Math.Min(s.Height, area.Height)); }

        static string WindowFile { get { return Path.Combine(Program.DataDir, "window.txt"); } }
        static bool ReadOnly { get { return Environment.GetEnvironmentVariable("HIB_READONLY") == "1"; } }

        // Opens where it was last closed if that is still on a screen; otherwise centred on the
        // screen with the mouse, at a comfortable size that fits its work area.
        void PlaceWindow()
        {
            StartPosition = FormStartPosition.Manual;
            Rectangle area = Screen.FromPoint(Cursor.Position).WorkingArea;
            int dpi = DpiAt(new Point(area.Left + area.Width / 2, area.Top + area.Height / 2));
            Size size = Fit(Scale(Preferred, dpi), new Rectangle(0, 0, area.Width * 94 / 100, area.Height * 94 / 100));
            Point at = new Point(area.Left + (area.Width - size.Width) / 2, area.Top + (area.Height - size.Height) / 2);
            bool maximized = false;
            try
            {
                if (!ReadOnly && File.Exists(WindowFile))
                {
                    // "x y width height maximized": position in pixels, size in logical pixels.
                    int[] v = File.ReadAllText(WindowFile).Trim().Split(' ').Select(int.Parse).ToArray();
                    Point p = new Point(v[0], v[1]);
                    Screen saved = Screen.AllScreens.FirstOrDefault(sc => sc.WorkingArea.Contains(new Point(p.X + 60, p.Y + 20)));
                    if (saved != null && v.Length >= 4)
                    {
                        area = saved.WorkingArea;
                        dpi = DpiAt(p);
                        size = Fit(Scale(new Size(Math.Max(v[2], Smallest.Width), Math.Max(v[3], Smallest.Height)), dpi), area);
                        at = new Point(Math.Max(area.Left, Math.Min(p.X, area.Right - size.Width)),
                                       Math.Max(area.Top, Math.Min(p.Y, area.Bottom - size.Height)));
                        maximized = v.Length > 4 && v[4] == 1;
                    }
                }
            }
            catch { }
            MinimumSize = Fit(Scale(Smallest, dpi), area);
            Bounds = new Rectangle(at, size);
            if (maximized) WindowState = FormWindowState.Maximized;
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            base.OnFormClosing(e);
            if (ReadOnly || full) return;   // tests never change the saved window
            try
            {
                Rectangle b = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                int dpi = 96;
                try { dpi = (int)GetDpiForWindow(Handle); } catch { }
                if (dpi <= 0) dpi = 96;
                Directory.CreateDirectory(Program.DataDir);
                File.WriteAllText(WindowFile, string.Join(" ", new[] { b.X, b.Y, b.Width * 96 / dpi, b.Height * 96 / dpi,
                    WindowState == FormWindowState.Maximized ? 1 : 0 }));
            }
            catch { }
        }

        // Moved to a screen with other scaling: take the rectangle Windows suggests so the window
        // keeps its size on screen, and scale the minimum size to match.
        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_DPICHANGED)
            {
                int dpi = (int)((long)m.WParam & 0xFFFF);
                var r = (RECT)Marshal.PtrToStructure(m.LParam, typeof(RECT));
                Rectangle area = Screen.FromRectangle(Rectangle.FromLTRB(r.Left, r.Top, r.Right, r.Bottom)).WorkingArea;
                MinimumSize = new Size(1, 1);
                SetWindowPos(Handle, IntPtr.Zero, r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top, 0x0004 | 0x0010); // NOZORDER | NOACTIVATE
                MinimumSize = Fit(Scale(Smallest, dpi), area);
                m.Result = IntPtr.Zero;
                return;
            }
            base.WndProc(ref m);
        }

        // Tests and the demo recorder can run beside an open copy of the app with their own browser folder.
        static string WebViewDir()
        {
            string dir = Environment.GetEnvironmentVariable("HIB_WEBVIEW_DIR");
            if (Environment.GetEnvironmentVariable("HIB_READONLY") == "1" && !string.IsNullOrEmpty(dir)) return dir;
            return Path.Combine(Program.DataDir, "WebView");
        }

        async Task Start()
        {
            try
            {
                CoreWebView2Environment.SetLoaderDllFolderPath(Program.LoaderDir);
                var env = await CoreWebView2Environment.CreateAsync(null, WebViewDir());
                await web.EnsureCoreWebView2Async(env);
            }
            catch (Exception ex)
            {
                // Windows 11 always has WebView2; a few Windows 10 PCs don't yet.
                var answer = MessageBox.Show(this, "Hib Clean PC needs Microsoft Edge WebView2. It comes with Windows 11; on Windows 10 "
                    + "it is a free download from Microsoft.\n\nOpen the download page now?\n\n(" + ex.Message + ")",
                    "Hib Clean PC", MessageBoxButtons.YesNo, MessageBoxIcon.Error);
                if (answer == DialogResult.Yes) OpenExternal("https://developer.microsoft.com/microsoft-edge/webview2/");
                Close();
                return;
            }
            var core = web.CoreWebView2;
            core.Settings.AreDevToolsEnabled = Environment.GetEnvironmentVariable("HIB_DEVTOOLS") == "1";
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsZoomControlEnabled = false;
            // The app only shows its own local pages, so there is nothing to check with SmartScreen online.
            core.Settings.IsReputationCheckingRequired = false;
            core.SetVirtualHostNameToFolderMapping(Program.Host, Program.Res("ui"), CoreWebView2HostResourceAccessKind.Deny);
            core.WebMessageReceived += OnMessage;
            // Camera and microphone, for the used-laptop check, only for our own page.
            core.PermissionRequested += (s, e) =>
            {
                bool ours = e.Uri.StartsWith("https://" + Program.Host + "/");
                bool media = e.PermissionKind == CoreWebView2PermissionKind.Camera
                    || e.PermissionKind == CoreWebView2PermissionKind.Microphone;
                e.State = ours && media ? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Deny;
            };
            // Never navigate away from the app; links open in the default browser.
            core.NavigationStarting += (s, e) =>
            {
                if (!e.Uri.StartsWith("https://" + Program.Host + "/")) { e.Cancel = true; OpenExternal(e.Uri); }
            };
            core.NewWindowRequested += (s, e) => { e.Handled = true; OpenExternal(e.Uri); };
            core.Navigate(startPage);
        }

        static void OpenExternal(string uri)
        {
            // windowsdefender: only opens pages of the Windows Security app (for the security check).
            if (Regex.IsMatch(uri ?? "", @"^(https://|ms-settings:|ms-windows-store:|windowsdefender://[a-z]+/?$)", RegexOptions.IgnoreCase))
            {
                try { Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true }); } catch { }
            }
        }

        void OnMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            if (!e.Source.StartsWith("https://" + Program.Host + "/")) return;
            Dictionary<string, object> msg;
            try { msg = json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson); }
            catch { return; }
            object id; msg.TryGetValue("id", out id);
            string cmd = msg.ContainsKey("cmd") ? msg["cmd"] as string : null;
            object args = msg.ContainsKey("args") ? msg["args"] : null;
            bool admin = msg.ContainsKey("admin") && msg["admin"] is bool && (bool)msg["admin"];
            Reply(id, cmd, args, admin);
        }

        async void Reply(object id, string cmd, object args, bool admin)
        {
            string reply;
            try
            {
                string data = await Dispatch(cmd, args, admin);
                reply = "{\"id\":" + json.Serialize(id) + ",\"ok\":true,\"data\":" + (string.IsNullOrWhiteSpace(data) ? "null" : data) + "}";
            }
            catch (Exception ex)
            {
                reply = "{\"id\":" + json.Serialize(id) + ",\"ok\":false,\"error\":" + json.Serialize(ex.Message) + "}";
            }
            try { web.CoreWebView2.PostWebMessageAsJson(reply); } catch { }
        }

        async Task<string> Dispatch(string cmd, object args, bool admin)
        {
            var a = args as Dictionary<string, object> ?? new Dictionary<string, object>();
            switch (cmd)
            {
                case "host.info":
                    return json.Serialize(new Dictionary<string, object> {
                        { "version", Program.Version },
                        { "lang", System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName },
                        { "admin", IsAdmin() },
                        // Windows 11 is build 22000 and later; a few features only exist there.
                        { "build", Environment.OSVersion.Version.Build },
                        { "arch", Program.Arch },
                    });
                case "host.fullscreen":
                    SetFullscreen(a.ContainsKey("on") && a["on"] is bool && (bool)a["on"]);
                    return "true";
                case "host.pdf":
                    return json.Serialize(await SavePdf(a.ContainsKey("name") ? a["name"] as string : null));
                case "host.open":
                    OpenExternal(a.ContainsKey("url") ? a["url"] as string : null);
                    return "true";
                case "host.reveal":
                {
                    string path = a.ContainsKey("path") ? a["path"] as string : null;
                    if (path != null && File.Exists(path)) Process.Start("explorer.exe", "/select,\"" + path + "\"");
                    return "true";
                }
            }
            if (cmd == null || !Regex.IsMatch(cmd, "^[a-z][a-z0-9-]{1,40}$")) throw new Exception("Unknown command");
            // Automated tests run the app read-only: nothing that changes the PC can run,
            // even if something in the window gets clicked.
            if (Environment.GetEnvironmentVariable("HIB_READONLY") == "1")
            {
                string mode = a.ContainsKey("mode") ? a["mode"] as string : null;
                if (mode != null && !Regex.IsMatch(mode, "^(scan|list|status|report)$")) throw new Exception("read-only test mode");
            }
            string script = Program.Res(Path.Combine("scripts", cmd + ".ps1"));
            if (!File.Exists(script)) throw new Exception("Unknown command: " + cmd);
            string payload = Convert.ToBase64String(Encoding.UTF8.GetBytes(json.Serialize(a)));
            return await Task.Run(() => admin && !IsAdmin() ? RunElevated(script, payload) : RunScript(script, payload));
        }

        static bool IsAdmin()
        {
            return new System.Security.Principal.WindowsPrincipal(System.Security.Principal.WindowsIdentity.GetCurrent())
                .IsInRole(System.Security.Principal.WindowsBuiltInRole.Administrator);
        }

        static string PowerShell()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
        }

        static string RunScript(string script, string payload)
        {
            var psi = new ProcessStartInfo(PowerShell(),
                "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"" + script + "\" -Payload " + payload)
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            using (var p = Process.Start(psi))
            {
                var err = p.StandardError.ReadToEndAsync();
                string output = p.StandardOutput.ReadToEnd();
                p.WaitForExit();
                return Result(output, err.Result, p.ExitCode);
            }
        }

        // UAC can't hand back a redirected stdout, so the script writes to a file.
        static string RunElevated(string script, string payload)
        {
            string outFile = Path.Combine(Path.GetTempPath(), "hibclean-" + Guid.NewGuid().ToString("N") + ".json");
            var psi = new ProcessStartInfo(PowerShell(),
                "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\" -Payload " + payload
                + " -OutFile \"" + outFile + "\"")
            { UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden };
            try
            {
                using (var p = Process.Start(psi))
                {
                    p.WaitForExit();
                    string output = File.Exists(outFile) ? File.ReadAllText(outFile, Encoding.UTF8) : "";
                    return Result(output, "", p.ExitCode);
                }
            }
            catch (System.ComponentModel.Win32Exception ex)
            {
                // 1223: the user said No to the UAC prompt.
                throw new Exception(ex.NativeErrorCode == 1223 ? "cancelled" : ex.Message);
            }
            finally
            {
                try { File.Delete(outFile); } catch { }
            }
        }

        static string Result(string output, string error, int exitCode)
        {
            output = (output ?? "").Trim().TrimStart('﻿');
            if (exitCode != 0 || output.Length == 0)
            {
                string why = (error ?? "").Trim();
                if (why.Length == 0) why = output.Length > 0 ? output : "The action failed (code " + exitCode + ").";
                if (why.Length > 400) why = why.Substring(0, 400);
                throw new Exception(why);
            }
            return output;
        }

        void SetFullscreen(bool on)
        {
            if (on == full) return;
            full = on;
            if (on)
            {
                beforeBorder = FormBorderStyle; beforeFull = WindowState;
                FormBorderStyle = FormBorderStyle.None; WindowState = FormWindowState.Normal; WindowState = FormWindowState.Maximized;
            }
            else
            {
                FormBorderStyle = beforeBorder; WindowState = beforeFull;
            }
        }

        async Task<Dictionary<string, object>> SavePdf(string name)
        {
            string safe = Regex.Replace(name ?? "Hib Clean PC report", @"[^\w \-]", "").Trim();
            if (safe.Length == 0) safe = "Hib Clean PC report";
            string dir = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            string path = Path.Combine(dir, safe + ".pdf");
            for (int i = 2; File.Exists(path); i++) path = Path.Combine(dir, safe + " (" + i + ").pdf");
            var settings = web.CoreWebView2.Environment.CreatePrintSettings();
            settings.ShouldPrintBackgrounds = true;
            settings.ShouldPrintHeaderAndFooter = false;
            settings.MarginTop = settings.MarginBottom = 0.4;
            settings.MarginLeft = settings.MarginRight = 0.4;
            bool ok = await web.CoreWebView2.PrintToPdfAsync(path, settings);
            if (!ok) throw new Exception("Couldn't save the PDF.");
            return new Dictionary<string, object> { { "path", path } };
        }
    }
}
