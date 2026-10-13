// capption-loopback: capture the audio of one process tree via WASAPI process loopback
// and write interleaved float32 PCM to stdout.
//
//   capption-loopback.exe --pid N [--rate 48000] [--channels 2]
//   capption-loopback.exe --probe        (exit 0 if process loopback can be activated)
//
// Based on Microsoft's ApplicationLoopback sample. The helper stops when stdin reaches EOF
// (the parent closed it or died), when stdout breaks, or when the target process exits.
// Gaps where the engine delivers no packets are filled with silence so the stream stays
// in real time. Diagnostics go to stderr.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <wrl/implements.h>

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <vector>

using Microsoft::WRL::ClassicCom;
using Microsoft::WRL::ComPtr;
using Microsoft::WRL::FtmBase;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;

enum ExitCode : int {
    kOk = 0,             // stopped by parent (stdin EOF) or stdout closed
    kBadArgs = 2,
    kUnsupported = 3,    // process loopback activation failed
    kTargetExited = 4,
    kDeviceLost = 5,     // audio engine/device went away
    kError = 6,
};

static void Log(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
    fflush(stderr);
}

// Completion handler for ActivateAudioInterfaceAsync. FtmBase makes it agile, which the
// API requires.
class ActivationHandler
    : public RuntimeClass<RuntimeClassFlags<ClassicCom>, FtmBase, IActivateAudioInterfaceCompletionHandler> {
public:
    ActivationHandler() { done_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); }
    ~ActivationHandler() override { CloseHandle(done_); }

    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* op) override {
        HRESULT hrActivate = E_FAIL;
        ComPtr<IUnknown> unk;
        HRESULT hr = op->GetActivateResult(&hrActivate, &unk);
        if (SUCCEEDED(hr)) hr = hrActivate;
        if (SUCCEEDED(hr)) hr = unk.As(&client_);
        result_ = hr;
        SetEvent(done_);
        return S_OK;
    }

    HRESULT Wait(DWORD ms) {
        if (WaitForSingleObject(done_, ms) != WAIT_OBJECT_0) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
        return result_;
    }

    ComPtr<IAudioClient> client_;

private:
    HANDLE done_;
    HRESULT result_ = E_PENDING;
};

static HRESULT ActivateLoopback(DWORD pid, ComPtr<IAudioClient>& client) {
    AUDIOCLIENT_ACTIVATION_PARAMS params = {};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;

    PROPVARIANT pv = {};
    pv.vt = VT_BLOB;
    pv.blob.cbSize = sizeof(params);
    pv.blob.pBlobData = reinterpret_cast<BYTE*>(&params);

    auto handler = Microsoft::WRL::Make<ActivationHandler>();
    ComPtr<IActivateAudioInterfaceAsyncOperation> op;
    HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, __uuidof(IAudioClient), &pv,
                                             handler.Get(), &op);
    if (FAILED(hr)) return hr;
    hr = handler->Wait(5000);
    if (SUCCEEDED(hr)) client = handler->client_;
    return hr;
}

static std::atomic<bool> g_stdinClosed{false};

static DWORD WINAPI StdinWatcher(LPVOID) {
    HANDLE in = GetStdHandle(STD_INPUT_HANDLE);
    char buf[64];
    DWORD n = 0;
    while (ReadFile(in, buf, sizeof(buf), &n, nullptr) && n > 0) {
    }
    g_stdinClosed = true;
    return 0;
}

static bool WriteAll(HANDLE out, const void* data, size_t bytes) {
    const char* p = static_cast<const char*>(data);
    while (bytes > 0) {
        DWORD chunk = static_cast<DWORD>(bytes > (1u << 20) ? (1u << 20) : bytes);
        DWORD written = 0;
        if (!WriteFile(out, p, chunk, &written, nullptr) || written == 0) return false;
        p += written;
        bytes -= written;
    }
    return true;
}

static bool IsDeviceLost(HRESULT hr) {
    return hr == AUDCLNT_E_DEVICE_INVALIDATED || hr == AUDCLNT_E_SERVICE_NOT_RUNNING ||
           hr == AUDCLNT_E_RESOURCES_INVALIDATED;
}

static int Capture(DWORD pid, DWORD rate, WORD channels) {
    HANDLE target = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!target) {
        Log("cannot open process %lu (error %lu)", pid, GetLastError());
        return kTargetExited;
    }

    ComPtr<IAudioClient> client;
    HRESULT hr = ActivateLoopback(pid, client);
    if (FAILED(hr)) {
        Log("process loopback activation failed: 0x%08lx", hr);
        CloseHandle(target);
        return kUnsupported;
    }

    WAVEFORMATEX fmt = {};
    fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
    fmt.nChannels = channels;
    fmt.nSamplesPerSec = rate;
    fmt.wBitsPerSample = 32;
    fmt.nBlockAlign = static_cast<WORD>(channels * sizeof(float));
    fmt.nAvgBytesPerSec = rate * fmt.nBlockAlign;

    // Process loopback has no mix format; the engine converts to whatever we ask for.
    hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                                AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                            200 * 10000 /* 200 ms in 100-ns units */, 0, &fmt, nullptr);
    if (FAILED(hr)) {
        Log("IAudioClient::Initialize failed: 0x%08lx", hr);
        CloseHandle(target);
        return kUnsupported;
    }

    HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    ComPtr<IAudioCaptureClient> capture;
    if (FAILED(hr = client->SetEventHandle(ready)) || FAILED(hr = client->GetService(IID_PPV_ARGS(&capture))) ||
        FAILED(hr = client->Start())) {
        Log("capture setup failed: 0x%08lx", hr);
        CloseHandle(ready);
        CloseHandle(target);
        return kUnsupported;
    }
    Log("capturing pid %lu at %lu Hz x%u float32", pid, rate, channels);

    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    std::vector<float> silence;
    LARGE_INTEGER freq, start, now;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);
    unsigned long long framesWritten = 0;
    const unsigned long long slack = rate / 5;  // tolerate 200 ms of jitter before padding

    int code = kOk;
    HANDLE waits[2] = {ready, target};
    while (code == kOk && !g_stdinClosed) {
        DWORD w = WaitForMultipleObjects(2, waits, FALSE, 100);
        if (w == WAIT_OBJECT_0 + 1) {
            Log("target process exited");
            code = kTargetExited;
            break;
        }
        if (w == WAIT_FAILED) {
            code = kError;
            break;
        }

        UINT32 packet = 0;
        while (SUCCEEDED(hr = capture->GetNextPacketSize(&packet)) && packet > 0) {
            BYTE* data = nullptr;
            UINT32 frames = 0;
            DWORD flags = 0;
            hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) break;
            size_t bytes = static_cast<size_t>(frames) * fmt.nBlockAlign;
            bool ok;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                silence.assign(static_cast<size_t>(frames) * channels, 0.0f);
                ok = WriteAll(out, silence.data(), bytes);
            } else {
                ok = WriteAll(out, data, bytes);
            }
            capture->ReleaseBuffer(frames);
            if (!ok) {
                code = kOk;  // parent stopped reading
                g_stdinClosed = true;
                break;
            }
            framesWritten += frames;
        }
        if (FAILED(hr)) {
            Log("capture failed: 0x%08lx", hr);
            code = IsDeviceLost(hr) ? kDeviceLost : kError;
            break;
        }

        // Pad with silence when the engine sends nothing (e.g. the app is quiet).
        QueryPerformanceCounter(&now);
        unsigned long long expected =
            static_cast<unsigned long long>((now.QuadPart - start.QuadPart) * rate / freq.QuadPart);
        if (expected > framesWritten + slack) {
            unsigned long long gap = expected - framesWritten - slack / 2;
            silence.assign(static_cast<size_t>(gap) * channels, 0.0f);
            if (!WriteAll(out, silence.data(), silence.size() * sizeof(float))) break;
            framesWritten += gap;
        }
    }

    client->Stop();
    CloseHandle(ready);
    CloseHandle(target);
    return code;
}

int wmain(int argc, wchar_t** argv) {
    DWORD pid = 0;
    DWORD rate = 48000;
    long channels = 2;
    bool probe = false;
    for (int i = 1; i < argc; ++i) {
        if (!wcscmp(argv[i], L"--probe")) {
            probe = true;
        } else if (!wcscmp(argv[i], L"--pid") && i + 1 < argc) {
            pid = wcstoul(argv[++i], nullptr, 10);
        } else if (!wcscmp(argv[i], L"--rate") && i + 1 < argc) {
            rate = wcstoul(argv[++i], nullptr, 10);
        } else if (!wcscmp(argv[i], L"--channels") && i + 1 < argc) {
            channels = wcstol(argv[++i], nullptr, 10);
        } else {
            Log("unknown argument: %ls", argv[i]);
            return kBadArgs;
        }
    }
    if ((!probe && pid == 0) || rate < 8000 || rate > 192000 || channels < 1 || channels > 8) {
        Log("usage: capption-loopback --pid N [--rate 48000] [--channels 2] | --probe");
        return kBadArgs;
    }

    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return kError;

    int code;
    if (probe) {
        ComPtr<IAudioClient> client;
        HRESULT hr = ActivateLoopback(GetCurrentProcessId(), client);
        if (FAILED(hr)) Log("process loopback activation failed: 0x%08lx", hr);
        code = SUCCEEDED(hr) ? kOk : kUnsupported;
    } else {
        HANDLE watcher = CreateThread(nullptr, 0, StdinWatcher, nullptr, 0, nullptr);
        code = Capture(pid, rate, static_cast<WORD>(channels));
        if (watcher) CloseHandle(watcher);
    }
    CoUninitialize();
    fflush(stderr);
    // The stdin watcher may still be blocked in ReadFile; don't wait for it.
    ExitProcess(static_cast<UINT>(code));
}
