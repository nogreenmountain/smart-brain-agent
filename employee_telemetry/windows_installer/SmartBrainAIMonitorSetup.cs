using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("SmartBrain AI Monitor Setup")]
[assembly: AssemblyDescription("SmartBrain AI Monitor self-service installer")]
[assembly: AssemblyCompany("SmartBrain")]
[assembly: AssemblyProduct("SmartBrain AI Monitor")]
[assembly: AssemblyVersion("2026.8.7.15")]
[assembly: AssemblyFileVersion("2026.8.7.15")]

namespace SmartBrain.AIMonitor.Setup
{
    internal static class Program
    {
        internal const string ProductName = "SmartBrain AI Monitor";
        internal const string ProductVersion = "2026.08.07.15";
        internal const string ResourceName = "SmartBrainPayload.zip";
        internal const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\SmartBrainAIMonitor";
        internal const string UrlProtocolKey = @"Software\Classes\smartbrain-ai-monitor";

        internal static string InstallRoot
        {
            get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SmartBrainAIMonitor"); }
        }

        internal static string PayloadRoot
        {
            get { return Path.Combine(InstallRoot, "payload"); }
        }

        internal static string InstalledExecutable
        {
            get { return Path.Combine(InstallRoot, "SmartBrainAIMonitorSetup.exe"); }
        }

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            try
            {
                if (args.Length >= 2 && args[0] == "--extract-only")
                {
                    ExtractPayload(args[1]);
                    return 0;
                }
                if (args.Length >= 3 && args[0] == "--cleanup")
                {
                    CleanupInstalledFiles(args[1], args[2]);
                    return 0;
                }
                if (args.Length >= 2 && args[0] == "--sync-cc-switch")
                    return RunCcSwitchSync(args[1]);
                Application.Run(new SetupForm(args.Length > 0 && args[0] == "--uninstall"));
                return 0;
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, ProductName, MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        internal static void ExtractPayload(string destination)
        {
            Directory.CreateDirectory(destination);
            string root = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream(ResourceName);
            if (resource == null) throw new InvalidOperationException("Installer payload is missing.");
            using (resource)
            using (ZipArchive archive = new ZipArchive(resource, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string target = Path.GetFullPath(Path.Combine(destination, entry.FullName));
                    if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("Installer payload contains an invalid path.");
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(target);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (Stream input = entry.Open())
                    using (FileStream output = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None))
                        input.CopyTo(output);
                }
            }
        }

        private static void CleanupInstalledFiles(string rootArgument, string processIdArgument)
        {
            string expected = Path.GetFullPath(InstallRoot).TrimEnd(Path.DirectorySeparatorChar);
            string requested = Path.GetFullPath(rootArgument).TrimEnd(Path.DirectorySeparatorChar);
            if (!string.Equals(expected, requested, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Refusing to remove an unexpected directory.");
            int processId;
            if (int.TryParse(processIdArgument, out processId))
            {
                try { Process.GetProcessById(processId).WaitForExit(15000); }
                catch (ArgumentException) { }
            }
            Thread.Sleep(500);
            if (Directory.Exists(requested)) Directory.Delete(requested, true);
        }

        private static int RunCcSwitchSync(string requestUri)
        {
            try
            {
                Uri uri = new Uri(requestUri);
                if (!string.Equals(uri.Scheme, "smartbrain-ai-monitor", StringComparison.OrdinalIgnoreCase) ||
                    !string.Equals(uri.Host, "sync-cc-switch", StringComparison.OrdinalIgnoreCase))
                    return 2;
                Match match = Regex.Match(uri.Query, @"(?:^|[?&])request_id=([^&]+)", RegexOptions.IgnoreCase);
                Guid requestId;
                if (!match.Success || !Guid.TryParse(Uri.UnescapeDataString(match.Groups[1].Value), out requestId))
                    return 2;

                string runtimeDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "AIWorkdayTelemetry",
                    "current"
                );
                string script = Path.Combine(runtimeDir, "CCSwitchUsageSync.py");
                string python = Path.Combine(PayloadRoot, "python-runtime", "python.exe");
                if (!File.Exists(script) || !File.Exists(python)) return 3;

                ProcessStartInfo start = new ProcessStartInfo
                {
                    FileName = python,
                    Arguments = QuoteArgument(script) + " --runtime-dir " + QuoteArgument(runtimeDir)
                        + " --trigger manual --request-id " + requestId.ToString("D"),
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                start.EnvironmentVariables["PYTHONUTF8"] = "1";
                using (Process process = Process.Start(start))
                {
                    if (process == null) return 4;
                    if (!process.WaitForExit(90000))
                    {
                        try { process.Kill(); } catch { }
                        return 5;
                    }
                    return process.ExitCode;
                }
            }
            catch
            {
                return 1;
            }
        }

        private static string QuoteArgument(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }
    }

    internal sealed class SetupForm : Form
    {
        private readonly bool uninstallMode;
        private readonly TextBox username = new TextBox();
        private readonly TextBox password = new TextBox();
        private readonly Label status = new Label();
        private readonly ProgressBar progress = new ProgressBar();
        private readonly Button primary = new Button();
        private readonly Button close = new Button();
        private readonly CheckBox openRecords = new CheckBox();
        private bool busy;

        internal SetupForm(bool uninstall)
        {
            uninstallMode = uninstall;
            Text = Program.ProductName;
            Icon = SystemIcons.Application;
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(620, uninstall ? 330 : 500);
            BackColor = Color.FromArgb(246, 248, 251);
            Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);
            BuildUi();
        }

        private static string T(string escaped)
        {
            return System.Text.RegularExpressions.Regex.Unescape(escaped);
        }

        private void BuildUi()
        {
            Panel header = new Panel { Dock = DockStyle.Top, Height = 105, BackColor = Color.White };
            Panel accent = new Panel { Location = new Point(0, 0), Size = new Size(8, 105), BackColor = Color.FromArgb(37, 99, 235) };
            Label title = new Label
            {
                AutoSize = true,
                Location = new Point(32, 22),
                Font = new Font(Font.FontFamily, 18F, FontStyle.Bold),
                ForeColor = Color.FromArgb(17, 24, 39),
                Text = uninstallMode ? T("\u5378\u8f7d AI Monitor") : T("\u5b89\u88c5 AI Monitor")
            };
            Label subtitle = new Label
            {
                AutoSize = true,
                Location = new Point(34, 64),
                ForeColor = Color.FromArgb(107, 114, 128),
                Text = uninstallMode
                    ? T("\u79fb\u9664\u672c\u673a\u7684\u76d1\u63a7\u914d\u7f6e\u3001\u540c\u6b65\u4efb\u52a1\u548c\u6d4f\u89c8\u5668\u5feb\u6377\u65b9\u5f0f")
                    : T("\u7edf\u4e00\u5b89\u88c5 CC Switch\u3001Codex / Claude \u5bf9\u8bdd\u540c\u6b65\u4e0e ChatGPT \u7f51\u9875\u76d1\u63a7")
            };
            header.Controls.Add(accent);
            header.Controls.Add(title);
            header.Controls.Add(subtitle);
            Controls.Add(header);

            int top = 130;
            if (!uninstallMode)
            {
                AddField(T("\u667a\u6167\u5927\u8111\u7528\u6237\u540d"), username, top, false);
                top += 78;
                AddField(T("\u5bc6\u7801"), password, top, true);
                top += 80;
                Label privacy = new Label
                {
                    Location = new Point(38, top),
                    Size = new Size(540, 42),
                    ForeColor = Color.FromArgb(75, 85, 99),
                    Text = T("\u5bc6\u7801\u53ea\u7528\u4e8e\u672c\u6b21\u8eab\u4efd\u7ed1\u5b9a\uff0c\u4e0d\u4f1a\u5199\u5165\u547d\u4ee4\u884c\u3001\u65e5\u5fd7\u6216\u672c\u5730\u914d\u7f6e\u3002")
                };
                Controls.Add(privacy);
                top += 54;
                openRecords.Location = new Point(38, top);
                openRecords.Size = new Size(360, 25);
                openRecords.Text = T("\u5b89\u88c5\u5b8c\u6210\u540e\u6253\u5f00 AI \u4f7f\u7528\u8bb0\u5f55");
                openRecords.Checked = true;
                Controls.Add(openRecords);
                top += 40;
            }
            else
            {
                Label warning = new Label
                {
                    Location = new Point(38, top),
                    Size = new Size(540, 72),
                    ForeColor = Color.FromArgb(55, 65, 81),
                    Text = T("\u8bf7\u5148\u4ece\u7cfb\u7edf\u6258\u76d8\u5b8c\u5168\u9000\u51fa CC Switch\u3002\r\n\u5378\u8f7d\u4e0d\u4f1a\u5220\u9664\u670d\u52a1\u5668\u4e0a\u5df2\u4e0a\u62a5\u7684 AI \u4f7f\u7528\u8bb0\u5f55\u3002")
                };
                Controls.Add(warning);
                top += 95;
            }

            status.Location = new Point(38, top);
            status.Size = new Size(540, 40);
            status.ForeColor = Color.FromArgb(75, 85, 99);
            status.Text = uninstallMode ? T("\u51c6\u5907\u5378\u8f7d") : T("\u51c6\u5907\u5b89\u88c5\uff0c\u8bf7\u5148\u5b8c\u5168\u9000\u51fa CC Switch");
            Controls.Add(status);

            progress.Location = new Point(38, top + 43);
            progress.Size = new Size(540, 8);
            progress.Style = ProgressBarStyle.Marquee;
            progress.MarqueeAnimationSpeed = 0;
            Controls.Add(progress);

            primary.Location = new Point(368, ClientSize.Height - 58);
            primary.Size = new Size(100, 34);
            primary.FlatStyle = FlatStyle.Flat;
            primary.FlatAppearance.BorderSize = 0;
            primary.BackColor = Color.FromArgb(37, 99, 235);
            primary.ForeColor = Color.White;
            primary.Text = uninstallMode ? T("\u7acb\u5373\u5378\u8f7d") : T("\u7acb\u5373\u5b89\u88c5");
            primary.Click += delegate { StartOperation(); };
            Controls.Add(primary);

            close.Location = new Point(478, ClientSize.Height - 58);
            close.Size = new Size(100, 34);
            close.Text = T("\u53d6\u6d88");
            close.Click += delegate { Close(); };
            Controls.Add(close);
            AcceptButton = primary;
            CancelButton = close;
        }

        private void AddField(string labelText, TextBox box, int top, bool secret)
        {
            Label label = new Label { Location = new Point(38, top), AutoSize = true, ForeColor = Color.FromArgb(55, 65, 81), Text = labelText };
            box.Location = new Point(38, top + 25);
            box.Size = new Size(540, 30);
            box.BorderStyle = BorderStyle.FixedSingle;
            if (secret) box.PasswordChar = '\u25cf';
            Controls.Add(label);
            Controls.Add(box);
        }

        private void StartOperation()
        {
            if (busy) return;
            if (!uninstallMode && (string.IsNullOrWhiteSpace(username.Text) || password.Text.Length == 0))
            {
                MessageBox.Show(T("\u8bf7\u8f93\u5165\u7528\u6237\u540d\u548c\u5bc6\u7801\u3002"), Program.ProductName, MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            string loginName = username.Text.Trim();
            if (!Regex.IsMatch(loginName, @"^[A-Za-z0-9._@-]{1,254}$"))
            {
                MessageBox.Show(T("\u7528\u6237\u540d\u53ea\u80fd\u5305\u542b\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u70b9\u3001\u4e0b\u5212\u7ebf\u3001@ \u6216\u8fde\u5b57\u7b26\u3002"), Program.ProductName, MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            string loginPassword = password.Text;
            password.Clear();
            SetBusy(true, uninstallMode ? T("\u6b63\u5728\u5378\u8f7d\u2026") : T("\u6b63\u5728\u68c0\u67e5\u73af\u5883\u2026"));
            Thread worker = new Thread(delegate()
            {
                try
                {
                    if (uninstallMode) Uninstall(); else Install(loginName, loginPassword);
                    BeginInvoke((MethodInvoker)delegate
                    {
                        SetBusy(false, uninstallMode ? T("\u5378\u8f7d\u5b8c\u6210") : T("\u5b89\u88c5\u5b8c\u6210\uff0c\u5bf9\u8bdd\u5c06\u6bcf 2 \u5206\u949f\u81ea\u52a8\u540c\u6b65"));
                        primary.Enabled = false;
                        close.Text = T("\u5b8c\u6210");
                        if (!uninstallMode && openRecords.Checked)
                            Process.Start("http://192.168.1.40:3002/workday");
                    });
                }
                catch (Exception error)
                {
                    BeginInvoke((MethodInvoker)delegate
                    {
                        SetBusy(false, T("\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u6839\u636e\u63d0\u793a\u5904\u7406\u540e\u91cd\u8bd5"));
                        MessageBox.Show(error.Message, Program.ProductName, MessageBoxButtons.OK, MessageBoxIcon.Error);
                    });
                }
            });
            worker.IsBackground = true;
            worker.SetApartmentState(ApartmentState.STA);
            worker.Start();
        }

        private void SetBusy(bool value, string message)
        {
            busy = value;
            username.Enabled = !value;
            password.Enabled = !value;
            primary.Enabled = !value;
            close.Enabled = !value;
            progress.MarqueeAnimationSpeed = value ? 30 : 0;
            status.Text = message;
        }

        private void Install(string loginName, string loginPassword)
        {
            EnsureCcSwitchClosed();
            string stage = Path.Combine(Program.InstallRoot, ".stage-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Program.InstallRoot);
            try
            {
                Program.ExtractPayload(stage);
                ValidatePayload(stage);
                if (Directory.Exists(Program.PayloadRoot)) Directory.Delete(Program.PayloadRoot, true);
                Directory.Move(stage, Program.PayloadRoot);
                File.Copy(Application.ExecutablePath, Program.InstalledExecutable, true);
                SetStatus(T("\u6b63\u5728\u9a8c\u8bc1\u8d26\u53f7\u5e76\u5b89\u88c5\u76d1\u63a7\u7ec4\u4ef6\u2026"));
                string script = Path.Combine(Program.PayloadRoot, "Install-AIMonitor.ps1");
                string python = Path.Combine(Program.PayloadRoot, "python-runtime", "python.exe");
                string arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(script)
                    + " -Username " + Quote(loginName)
                    + " -PasswordFromStdin -PythonPath " + Quote(python)
                    + " -NonInteractive";
                RunPowerShell(arguments, loginPassword + Environment.NewLine);
                RegisterUninstaller();
                RegisterUrlProtocol();
            }
            finally
            {
                if (Directory.Exists(stage)) Directory.Delete(stage, true);
                loginPassword = string.Empty;
            }
        }

        private void Uninstall()
        {
            EnsureCcSwitchClosed();
            if (Directory.Exists(Program.PayloadRoot))
            {
                string script = Path.Combine(Program.PayloadRoot, "Uninstall-AIMonitor.ps1");
                string python = Path.Combine(Program.PayloadRoot, "python-runtime", "python.exe");
                if (File.Exists(script))
                    RunPowerShell("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(script) + " -PythonPath " + Quote(python) + " -NonInteractive", null);
            }
            using (RegistryKey root = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall", true))
                if (root != null) root.DeleteSubKeyTree("SmartBrainAIMonitor", false);
            using (RegistryKey classes = Registry.CurrentUser.OpenSubKey(@"Software\Classes", true))
                if (classes != null) classes.DeleteSubKeyTree("smartbrain-ai-monitor", false);
            string cleanupCopy = Path.Combine(Path.GetTempPath(), "SmartBrainAIMonitorCleanup-" + Guid.NewGuid().ToString("N") + ".exe");
            File.Copy(Application.ExecutablePath, cleanupCopy, true);
            Process.Start(new ProcessStartInfo
            {
                FileName = cleanupCopy,
                Arguments = "--cleanup " + Quote(Program.InstallRoot) + " " + Process.GetCurrentProcess().Id,
                UseShellExecute = false,
                CreateNoWindow = true
            });
        }

        private void SetStatus(string value)
        {
            BeginInvoke((MethodInvoker)delegate { status.Text = value; });
        }

        private static void EnsureCcSwitchClosed()
        {
            if (Process.GetProcessesByName("cc-switch").Length > 0)
                throw new InvalidOperationException(T("\u8bf7\u5148\u4ece\u7cfb\u7edf\u6258\u76d8\u5b8c\u5168\u9000\u51fa CC Switch\uff0c\u518d\u91cd\u8bd5\u3002"));
        }

        private static void ValidatePayload(string root)
        {
            foreach (string relative in new[] { "Install-AIMonitor.ps1", "Uninstall-AIMonitor.ps1", "manifest.json", @"python-runtime\python.exe" })
                if (!File.Exists(Path.Combine(root, relative))) throw new InvalidOperationException("Installer payload is incomplete: " + relative);
        }

        private static string Quote(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private static void RunPowerShell(string arguments, string standardInput)
        {
            StringBuilder output = new StringBuilder();
            ProcessStartInfo start = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = arguments,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            start.EnvironmentVariables["PYTHONUTF8"] = "1";
            using (Process process = new Process { StartInfo = start })
            {
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) output.AppendLine(e.Data); };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) output.AppendLine(e.Data); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                if (standardInput != null) process.StandardInput.Write(standardInput);
                process.StandardInput.Close();
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    string message = output.ToString().Trim();
                    throw new InvalidOperationException(string.IsNullOrEmpty(message) ? T("\u5b89\u88c5\u811a\u672c\u6267\u884c\u5931\u8d25\u3002") : message);
                }
            }
        }

        private static void RegisterUninstaller()
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Program.UninstallKey))
            {
                key.SetValue("DisplayName", Program.ProductName);
                key.SetValue("DisplayVersion", Program.ProductVersion);
                key.SetValue("Publisher", T("\u667a\u6167\u5927\u8111"));
                key.SetValue("DisplayIcon", Program.InstalledExecutable);
                key.SetValue("InstallLocation", Program.InstallRoot);
                key.SetValue("UninstallString", Quote(Program.InstalledExecutable) + " --uninstall");
                key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
        }

        private static void RegisterUrlProtocol()
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Program.UrlProtocolKey))
            {
                key.SetValue(null, "URL:SmartBrain AI Monitor Protocol");
                key.SetValue("URL Protocol", "");
                using (RegistryKey command = key.CreateSubKey(@"shell\open\command"))
                    command.SetValue(null, Quote(Program.InstalledExecutable) + " --sync-cc-switch \"%1\"");
            }
        }
    }
}
