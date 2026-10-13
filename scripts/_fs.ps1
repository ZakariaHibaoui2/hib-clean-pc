# File walking and deleting through Windows' own functions, with the \\?\ prefix,
# so folders deeper than 260 characters (common in temp folders) are handled too.
# Windows PowerShell 5.1 can't open those paths with its usual commands.
#
#   [HibFs]::Scan(root, pattern, recurse)   files (Path, Size, Write in UTC) and folders under root;
#                                           never crosses junctions or symlinks
#   [HibFs]::Delete(path)                   deletes one file, clearing read-only first if needed
#   [HibFs]::RemoveIfEmpty(path)            removes a folder only if it is empty

if (-not ('HibFs' -as [type])) {
# Add-Type compiles through the TEMP folder; use our own folder so a broken TEMP can't stop it.
$savedTmp = $env:TMP; $savedTemp = $env:TEMP
$compileDir = Join-Path $script:AppData 'compile'
New-Item -ItemType Directory -Force -Path $compileDir | Out-Null
$env:TMP = $compileDir; $env:TEMP = $compileDir
try {
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

public static class HibFs
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct FindData
    {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
        public uint SizeHigh, SizeLow, Reserved0, Reserved1;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string Name;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)] public string ShortName;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr FindFirstFileExW(string path, int infoLevel, out FindData data, int searchOp, IntPtr filter, int flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool FindNextFileW(IntPtr handle, out FindData data);
    [DllImport("kernel32.dll")] static extern bool FindClose(IntPtr handle);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool DeleteFileW(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool RemoveDirectoryW(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool SetFileAttributesW(string path, uint attributes);

    const uint Directory = 0x10, ReparsePoint = 0x400, Normal = 0x80;

    public class Entry { public string Path; public long Size; public DateTime Write; }
    public class Result
    {
        public List<Entry> Files = new List<Entry>();
        public List<string> Dirs = new List<string>();
        public bool Readable = true;
    }

    static string Long(string path)
    {
        if (path.StartsWith(@"\\?\")) return path;
        if (path.StartsWith(@"\\")) return @"\\?\UNC\" + path.Substring(2);
        return @"\\?\" + path;
    }

    public static Result Scan(string root, string pattern, bool recurse)
    {
        var result = new Result();
        Regex match = string.IsNullOrEmpty(pattern) ? null
            : new Regex("^" + Regex.Escape(pattern).Replace(@"\*", ".*").Replace(@"\?", ".") + "$", RegexOptions.IgnoreCase);
        string top = root.TrimEnd('\\');
        var stack = new Stack<string>();
        stack.Push(top);
        while (stack.Count > 0)
        {
            string dir = stack.Pop();
            FindData data;
            IntPtr handle = FindFirstFileExW(Long(dir) + @"\*", 1, out data, 0, IntPtr.Zero, 2);
            if (handle == new IntPtr(-1))
            {
                if (dir == top) result.Readable = false;
                continue;
            }
            try
            {
                do
                {
                    if (data.Name == "." || data.Name == "..") continue;
                    string full = dir + "\\" + data.Name;
                    bool isDir = (data.Attributes & Directory) != 0;
                    bool reparse = (data.Attributes & ReparsePoint) != 0;
                    if (reparse) continue;   // junctions and symlinks lead elsewhere: never follow or delete through them
                    if (isDir)
                    {
                        if (recurse) { stack.Push(full); result.Dirs.Add(full); }
                        continue;
                    }
                    if (match != null && !match.IsMatch(data.Name)) continue;
                    long size = ((long)data.SizeHigh << 32) | data.SizeLow;
                    long time = ((long)(uint)data.Written.dwHighDateTime << 32) | (uint)data.Written.dwLowDateTime;
                    result.Files.Add(new Entry { Path = full, Size = size, Write = DateTime.FromFileTimeUtc(time) });
                } while (FindNextFileW(handle, out data));
            }
            finally { FindClose(handle); }
        }
        return result;
    }

    public static bool Delete(string path)
    {
        string p = Long(path);
        if (DeleteFileW(p)) return true;
        return SetFileAttributesW(p, Normal) && DeleteFileW(p);
    }

    public static bool RemoveIfEmpty(string path) { return RemoveDirectoryW(Long(path)); }
}
'@
} finally { $env:TMP = $savedTmp; $env:TEMP = $savedTemp }
}
