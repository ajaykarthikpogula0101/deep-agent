// Robin.exe: the double-click launcher. Runs the bundled Python with `-m app.launch` from the folder the exe
// sits in, with the same environment Start Robin.bat sets. Compiled at bundle-build time with the C# compiler
// that ships in .NET Framework (csc.exe); see scripts/build_bundle.py. Sign it with scripts/bundle/sign.ps1.
using System;
using System.Diagnostics;
using System.IO;

static class Robin
{
    static int Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(dir, "python", "python.exe");
        if (!File.Exists(python))
        {
            Console.WriteLine("python\\python.exe is missing next to Robin.exe. Unzip the whole Robin folder, then run it again.");
            Console.ReadLine();
            return 2;
        }
        var psi = new ProcessStartInfo(python, "-m app.launch " + string.Join(" ", args));
        psi.WorkingDirectory = dir;
        psi.UseShellExecute = false;
        psi.EnvironmentVariables["OPENBLAS_NUM_THREADS"] = "1";
        psi.EnvironmentVariables["OMP_NUM_THREADS"] = "1";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        string models = Path.Combine(dir, "models");
        if (Directory.Exists(models))
        {
            psi.EnvironmentVariables["FASTEMBED_CACHE_PATH"] = models;
            psi.EnvironmentVariables["HF_HUB_OFFLINE"] = "1";
        }
        Console.WriteLine("Starting Robin... keep this window open while you use Robin; close it to stop.");
        using (var p = Process.Start(psi))
        {
            p.WaitForExit();
            if (p.ExitCode != 0)
            {
                Console.WriteLine();
                Console.WriteLine("Robin stopped with an error. The message above says what to fix. Press Enter to close.");
                Console.ReadLine();
            }
            return p.ExitCode;
        }
    }
}
