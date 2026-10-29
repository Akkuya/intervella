using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

namespace UtscVacant {
    // A Windows job owns only our gated workers and their descendants, even on host termination.
    public sealed class DevProcesses : IDisposable {
        [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
            public long ProcessTime, JobTime;
            public uint Flags;
            public UIntPtr MinWorkingSet, MaxWorkingSet;
            public uint ActiveProcesses;
            public UIntPtr Affinity;
            public uint Priority, Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)] struct IoCounters {
            public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
        }
        [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
            public BasicLimits Basic;
            public IoCounters Io;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits info, uint size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        IntPtr job;
        readonly List<Process> workers = new List<Process>();
        readonly List<EventWaitHandle> gates = new List<EventWaitHandle>();
        readonly ConcurrentQueue<string> output = new ConcurrentQueue<string>();

        public DevProcesses() {
            job = CreateJobObject(IntPtr.Zero, null);
            var limits = new ExtendedLimits();
            limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits))) {
                Dispose();
                throw new InvalidOperationException("Cannot create a Windows process job; no servers were started.");
            }
        }
        static string Quote(string value) {
            // Windows CommandLineToArgvW escaping, including spaces and trailing backslashes.
            var result = new System.Text.StringBuilder("\"");
            int slashes = 0;
            foreach (char character in value) {
                if (character == '\\') { slashes++; continue; }
                result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
                result.Append(character);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }
        public Process Start(string executable, string[] arguments, string directory, string prefix) {
            var escaped = new List<string>();
            foreach (var argument in arguments) escaped.Add(Quote(argument));
            var info = new ProcessStartInfo(executable, string.Join(" ", escaped.ToArray()));
            info.WorkingDirectory = directory;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            string name = "Local\\utscvacant-start-" + Guid.NewGuid().ToString("N");
            var gate = new EventWaitHandle(false, EventResetMode.ManualReset, name);
            // PowerShell startup can be delayed; retain the named gate until workers exit.
            gates.Add(gate);
            {
                info.EnvironmentVariables["UTSCVACANT_START_GATE"] = name;
                var process = new Process();
                process.StartInfo = info;
                process.OutputDataReceived += (sender, args) => { if (args.Data != null) output.Enqueue("[" + prefix + "] " + args.Data); };
                process.ErrorDataReceived += (sender, args) => { if (args.Data != null) output.Enqueue("[" + prefix + "] " + args.Data); };
                process.Start();
                if (!AssignProcessToJobObject(job, process.Handle)) {
                    process.Kill();
                    process.WaitForExit();
                    throw new InvalidOperationException("Cannot safely own the worker process. No application was started.");
                }
                workers.Add(process);
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                gate.Set();
                return process;
            }
        }
        public bool TryRead(out string line) { return output.TryDequeue(out line); }
        public void Dispose() {
            if (job == IntPtr.Zero) return;
            CloseHandle(job);
            job = IntPtr.Zero;
            foreach (var worker in workers) {
                if (worker.WaitForExit(5000)) worker.WaitForExit(); // Drain asynchronous output too.
            }
            foreach (var gate in gates) gate.Dispose();
        }
    }
}
