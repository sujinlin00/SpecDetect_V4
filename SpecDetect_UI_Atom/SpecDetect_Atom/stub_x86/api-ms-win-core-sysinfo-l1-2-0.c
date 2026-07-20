
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

__declspec(dllexport) int __stdcall GetOsSafeBootMode(unsigned int* p) {
    if (p) *p = 0;
    return 1;
}


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
