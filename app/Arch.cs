// Which native WebView2Loader.dll this process needs: x86, x64 or arm64.
// Kept apart from HibCleanPC.cs so tests/test_devices.py can compile and check it alone.
// C# 5 only (built with the compiler that comes with Windows).
using System;
using System.Runtime.InteropServices;

namespace HibCleanPC
{
    public static class Arch
    {
        public const ushort MachineX86 = 0x014c;
        public const ushort MachineX64 = 0x8664;
        public const ushort MachineArm64 = 0xAA64;

        // The loader for a PE "Machine" value, or null if the app has none for it.
        public static string FromMachine(ushort machine)
        {
            switch (machine)
            {
                case MachineX86: return "x86";
                case MachineX64: return "x64";
                case MachineArm64: return "arm64";
            }
            return null;
        }

        // From PROCESSOR_ARCHITECTURE as Windows sets it for this process (x86, AMD64, ARM64)
        // and the pointer size. A 32-bit process always needs the x86 loader.
        public static string FromEnvironment(string processorArchitecture, int pointerSize)
        {
            if (pointerSize == 4) return "x86";
            string a = (processorArchitecture ?? "").Trim().ToUpperInvariant();
            if (a == "ARM64") return "arm64";
            return "x64";
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetModuleHandle(string name);

        // The architecture this process really runs as. On Windows 11 ARM, .NET Framework 4.8.1
        // runs an AnyCPU app natively as ARM64; older .NET runs it as x64 under emulation.
        // kernel32 is mapped with this process's own machine type in its header (ARM64X system
        // files show x64 to emulated processes), which tells the two apart reliably.
        public static string Current()
        {
            if (IntPtr.Size == 4) return "x86";
            try
            {
                IntPtr k = GetModuleHandle("kernel32.dll");
                if (k != IntPtr.Zero && Marshal.ReadInt16(k) == 0x5A4D)          // "MZ"
                {
                    int pe = Marshal.ReadInt32(k, 0x3C);
                    if (Marshal.ReadInt32(k, pe) == 0x00004550)                   // "PE\0\0"
                    {
                        string m = FromMachine((ushort)Marshal.ReadInt16(k, pe + 4));
                        if (m != null) return m;
                    }
                }
            }
            catch { }
            return FromEnvironment(Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE"), IntPtr.Size);
        }

        // The name the loader for an architecture is embedded under in the exe.
        public static string Resource(string arch)
        {
            return "WebView2Loader." + arch + ".dll";
        }
    }
}
