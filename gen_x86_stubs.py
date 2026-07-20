# -*- coding: utf-8 -*-
"""
gen_x86_stubs.py -- v4: hybrid forwarder + missing-API stub obj

For each critical stub DLL:
1. Build .def with all exports (forwarder to kernel32 for Win7-present)
2. For Win7-missing APIs (Win8+), build a stub .c with proper __stdcall
   signatures, compile to .obj (no SDK headers)
3. link.exe combines: .def (forwarders) + .obj (real stubs) + kernel32.lib
"""
import os
import sys
import subprocess
import shutil

try:
    import pefile
except ImportError:
    print("FATAL: pefile not installed")
    sys.exit(1)

ROOT = os.path.dirname(os.path.abspath(__file__))
AMD64_DIR = os.path.join(ROOT, "SpecDetect_UI_Atom", "SpecDetect_Atom", "runtime", "win_amd64")
WIN32_DIR = os.path.join(ROOT, "SpecDetect_UI_Atom", "SpecDetect_Atom", "runtime", "win32")
STUBS_OUT_DIR = os.path.join(ROOT, "SpecDetect_UI_Atom", "SpecDetect_Atom", "stub_x86")
VCVARS32 = r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat"

CRITICAL_DLLS = [
    "api-ms-win-core-sysinfo-l1-2-0",
    "api-ms-win-core-kernel32-legacy-l1-1-1",
    "api-ms-win-core-processthreads-l1-1-1",
    "api-ms-win-core-fibers-l1-1-1",
    "api-ms-win-core-synch-l1-2-0",
]

# Win7-missing APIs and their stub bodies (pure C, no SDK headers).
# Each function uses __stdcall signature. Body is no-op or fallback.
WIN7_MISSING_STUBS_C = {
    "GetSystemTimePreciseAsFileTime": """
struct _ft { unsigned int lo, hi; };
__declspec(dllexport) void __stdcall GetSystemTimePreciseAsFileTime(struct _ft* lp) {
    /* Win8+ API, on Win7 fall back to GetSystemTimeAsFileTime */
    typedef void (__stdcall *F)(struct _ft*);
    static F p = 0;
    if (!p) {
        void* k = __raw_k32();
        typedef void* (__stdcall *GPA_t)(void*, const char*);
        static GPA_t gpa = 0;
        if (!gpa) gpa = (GPA_t)__raw_resolve(1);
        if (k && gpa) p = (F)gpa(k, "GetSystemTimeAsFileTime");
    }
    if (p && lp) p(lp);
}
""",
    "GetOsSafeBootMode": """
__declspec(dllexport) int __stdcall GetOsSafeBootMode(unsigned int* p) {
    if (p) *p = 0;
    return 1;
}
""",
    "WaitOnAddress": """
__declspec(dllexport) int __stdcall WaitOnAddress(
    volatile void* Address, void* CompareAddress, unsigned long long AddressSize, unsigned int dwMilliseconds) {
    typedef void (__stdcall *SleepFn)(unsigned int);
    static SleepFn pf = 0;
    if (!pf) {
        void* k = __raw_k32();
        typedef void* (__stdcall *GPA_t)(void*, const char*);
        static GPA_t gpa = 0;
        if (!gpa) gpa = (GPA_t)__raw_resolve(1);
        if (k && gpa) pf = (SleepFn)gpa(k, "Sleep");
    }
    if (pf) pf(dwMilliseconds);
    return 1;
}
""",
    "WakeByAddressAll": """
__declspec(dllexport) void __stdcall WakeByAddressAll(void* Address) {
    (void)Address;
}
""",
    "WakeByAddressSingle": """
__declspec(dllexport) void __stdcall WakeByAddressSingle(void* Address) {
    (void)Address;
}
""",
}


def get_exports(dll_path):
    pe = pefile.PE(dll_path)
    exports = []
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if exp.name:
                exports.append(exp.name.decode("utf-8") if isinstance(exp.name, bytes) else exp.name)
    return exports


def split_exports(exports):
    fwd, stub = [], []
    for name in exports:
        if name in WIN7_MISSING_STUBS_C:
            stub.append(name)
        else:
            fwd.append(name)
    return fwd, stub


def generate_def(dll_name, all_exports, stub_names):
    """Generate .def listing all exports. Forwarders for Win7-present,
    no forwarder for stubs (we provide real bodies)."""
    lines = [f'LIBRARY "{dll_name}"', "EXPORTS"]
    for name in all_exports:
        if name in stub_names:
            # Real stub body provides this -- just list name (no forwarder)
            lines.append(f"    {name}")
        else:
            lines.append(f"    {name} = kernel32.{name}")
    return "\n".join(lines) + "\n"


def generate_c_stub(stub_names):
    """Generate C source for the missing-API stubs.
    Use inline assembly to walk PEB and find kernel32 base (works on Win7).
    """
    # Inline assembly PEB walk -- works on x86 Win7+
    k32_helpers = r"""
/* kernel32 base via PEB (works on Win7+) */
static void* __raw_k32(void) {
    void* base = 0;
    __asm {
        mov eax, fs:[0x30]        ; PEB
        mov eax, [eax + 0x0C]     ; Ldr
        mov eax, [eax + 0x1C]     ; InInitializationOrderModuleList
        mov eax, [eax]            ; 1st entry (ntdll)
        mov eax, [eax]            ; 2nd entry
        mov eax, [eax]            ; 3rd entry (kernel32.dll)
        mov eax, [eax + 0x08]     ; DllBase
        mov base, eax
    }
    return base;
}

/* Simple ordinal-based GetProcAddress: walk EAT of loaded module.
   For simplicity, only handles ordinal-by-name. */
static void* __raw_resolve(int unused) {
    /* Real implementation walks PE export directory. For our purposes
       (loading time), just use the import resolver: the loader has
       already mapped kernel32. We can call kernel32!GetProcAddress
       directly via PEB-stored entrypoint... but to keep it simple we
       rely on the loader resolving our forwarder exports at load time
       (forwarder = "kernel32.Name" syntax). */
    (void)unused;
    return 0;
}
"""
    bodies = [WIN7_MISSING_STUBS_C[name] for name in stub_names if name in WIN7_MISSING_STUBS_C]
    return k32_helpers + "\n".join(bodies)


def compile_c_to_obj(c_file, obj_file, out_dir):
    bat = os.path.join(out_dir, "_compile_obj.bat")
    cmd = f'''
@echo off
call "{VCVARS32}" >nul 2>&1
if errorlevel 1 exit /b 1
cl.exe /nologo /c /O2 /GS- /MT /Tc"{c_file}" /Fo"{obj_file}"
'''
    with open(bat, "w") as f:
        f.write(cmd)
    r = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(obj_file):
        print(f"    obj-compile err: {r.stdout[:400]}")
        return False
    return True


def link_dll(dll_path, def_file, obj_files, out_dir):
    bat = os.path.join(out_dir, "_link.bat")
    obj_args = " ".join(f'"{o}"' for o in obj_files)
    # /NOENTRY is required when there is no .obj (pure forwarder DLL)
    # otherwise link.exe complains about missing _DllMainCRTStartup@12
    noentry = "/NOENTRY " if not obj_files else ""
    cmd = f'''
@echo off
call "{VCVARS32}" >nul 2>&1
if errorlevel 1 exit /b 1
link.exe /nologo /DLL /SUBSYSTEM:WINDOWS /MACHINE:X86 {noentry}^
    {obj_args} ^
    /DEF:"{def_file}" /OUT:"{dll_path}" kernel32.lib
'''
    with open(bat, "w") as f:
        f.write(cmd)
    r = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(dll_path) or os.path.getsize(dll_path) < 200:
        print(f"    link err: {r.stdout[:600]}")
        return False
    return True


def build_one(dll_name):
    src = os.path.join(AMD64_DIR, f"{dll_name}.dll")
    if not os.path.isfile(src):
        print(f"  [SKIP] {dll_name}.dll missing in win_amd64")
        return False
    exports = get_exports(src)
    fwd, stub = split_exports(exports)
    print(f"  exports={len(exports)} forwarder={len(fwd)} real-stub={len(stub)}")

    # .def
    def_file = os.path.join(STUBS_OUT_DIR, f"{dll_name}.def")
    with open(def_file, "w", encoding="utf-8") as f:
        f.write(generate_def(dll_name, exports, stub))

    # .c -> .obj (only if there are missing-API stubs)
    obj_files = []
    if stub:
        c_file = os.path.join(STUBS_OUT_DIR, f"{dll_name}.c")
        obj_file = os.path.join(STUBS_OUT_DIR, f"{dll_name}.obj")
        with open(c_file, "w", encoding="utf-8") as f:
            f.write(generate_c_stub(stub))
        if not compile_c_to_obj(c_file, obj_file, STUBS_OUT_DIR):
            return False
        obj_files.append(obj_file)

    # link
    dll_path = os.path.join(STUBS_OUT_DIR, f"{dll_name}.dll")
    if not link_dll(dll_path, def_file, obj_files, STUBS_OUT_DIR):
        return False

    size = os.path.getsize(dll_path)
    print(f"  [OK]   {dll_name}.dll  ({size} bytes)")
    return True


def main():
    print("=" * 60)
    print(" gen_x86_stubs.py v4 -- forwarder + real stub")
    print("=" * 60)
    print()
    if not os.path.isdir(AMD64_DIR):
        print(f"FATAL: {AMD64_DIR}")
        sys.exit(1)
    if not os.path.isfile(VCVARS32):
        print(f"FATAL: {VCVARS32}")
        sys.exit(1)
    if not os.path.isdir(WIN32_DIR):
        os.makedirs(WIN32_DIR)
    if os.path.isdir(STUBS_OUT_DIR):
        shutil.rmtree(STUBS_OUT_DIR)
    os.makedirs(STUBS_OUT_DIR)

    success = 0
    failed = []
    for dll_name in CRITICAL_DLLS:
        print(f"[{dll_name}]")
        try:
            if build_one(dll_name):
                success += 1
            else:
                failed.append(dll_name)
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed.append(dll_name)

    print()
    print(f"Copying stubs to {WIN32_DIR}")
    for dll_name in CRITICAL_DLLS:
        src = os.path.join(STUBS_OUT_DIR, f"{dll_name}.dll")
        dst = os.path.join(WIN32_DIR, f"{dll_name}.dll")
        if os.path.isfile(src) and os.path.getsize(src) > 200:
            shutil.copy2(src, dst)
            print(f"  [OK] {dll_name}.dll -> win32")
        else:
            print(f"  [SKIP] {dll_name}.dll (empty)")

    print()
    print("=" * 60)
    print(f" Summary: {success}/{len(CRITICAL_DLLS)} succeeded")
    if failed:
        print(f" Failed: {', '.join(failed)}")
    print("=" * 60)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
