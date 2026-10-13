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

        [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

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
            try { SetProcessDPIAware(); } catch { }
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
                string runtime = Path.Combine(temp, "runtime");
                Directory.CreateDirectory(runtime);
                using (var s = asm.GetManifestResourceStream("WebView2Loader.dll"))
                using (var f = File.Create(Path.Combine(runtime, "WebView2Loader.dll"))) s.CopyTo(f);
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
            MinimumSize = new Size(980, 660);
            StartPosition = FormStartPosition.CenterScreen;
            var area = Screen.PrimaryScreen.WorkingArea;
            Size = new Size(Math.Min(1240, area.Width - 80), Math.Min(820, area.Height - 60));
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
            try { DwmSetWindowAttribute(Handle, 20, ref on, 4); } catch { } // dark title bar
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
                CoreWebView2Environment.SetLoaderDllFolderPath(Program.Res("runtime"));
                var env = await CoreWebView2Environment.CreateAsync(null, WebViewDir());
                await web.EnsureCoreWebView2Async(env);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Hib Clean PC needs Microsoft Edge WebView2, which comes with Windows 11.\n\n" + ex.Message,
                    "Hib Clean PC", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
