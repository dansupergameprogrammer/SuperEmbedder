// tests/support/u3_alloc_hook.h -- U3 red suite: the real-allocation hooks of
// sec 4.6 row 5(d) (te266 P:4215) and C64's GPU leg (te267 P:3757). The test
// author's. INCLUDE IN EXACTLY ONE TRANSLATION UNIT PER BINARY: it defines the
// replaced global operator new/delete (every form, aligned and nothrow
// included), which also serve the statically linked engine.
//
// Host hook (d1, C64): counts the allocations made while armed or counting,
// and fails the k-th with the chosen fault: std::bad_alloc (C64 (a), row
// 5(d1)), std::length_error (C64 (a')), or a foreign exception type (C64 (b)).
// At the moment it fires it records where k fell, read through the GPU seam
// (semb_u3_gpu_seam.h): the running engine-call count and the number of
// threads inside an engine call. "Inside an engine call" is that number being
// nonzero; the call is the log record whose index equals that call count
// (the seam counts a call as it enters, so the count already includes it).
//
// Device hook (d2-d4, Windows only): ID3D12Device::CreateCommittedResource,
// vtable slot 27, which every device the D3D12 runtime creates shares (as
// TE-419's probe did). Installing it creates one throwaway device and patches
// the shared vtable; the engine's device then goes through it. Counts
// creations and fails the k-th with a chosen HRESULT (E_OUTOFMEMORY, or
// DXGI_ERROR_DEVICE_REMOVED for the must-reject), labelling each creation by
// its heap type.
#ifndef U3_ALLOC_HOOK_H
#define U3_ALLOC_HOOK_H

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>
#include <stdexcept>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <malloc.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#endif

#include "support/semb_u3_gpu_seam.h"

namespace u3hook {

enum Fault : int { kBadAlloc = 0, kLengthError = 1, kForeign = 2 };
struct ForeignFault {};  // C64 (b): an exception type no product frame names

struct HostState {
  std::atomic<int> counting{0};   // 1: count every allocation
  std::atomic<uint64_t> seen{0};  // allocations counted since Arm/Count
  std::atomic<uint64_t> target{0};  // 1-based k to fail; 0 = none
  std::atomic<int> fault{kBadAlloc};
  std::atomic<int> fired{0};
  std::atomic<uint64_t> fired_call_count{0};
  std::atomic<uint32_t> fired_occupancy{0};
  std::atomic<uint64_t> fired_size{0};  // the byte count the failed k asked for
  std::atomic<int64_t> live{0};  // live allocations, whole process
  // Segmentation (C64's GPU-open site plan): while `segmenting`, each counted
  // allocation is keyed by (inside an engine call?, the running call count),
  // and maximal runs of one key are recorded in fixed storage -- no
  // allocation inside the hook. A key is one engine call, or U3's own frames
  // between two engine calls. Each run also keeps its kTopSizes largest
  // allocations (k and bytes, largest first), so a plan can add the largest
  // sites of a class without a second counting run (row 5(d3h)'s sample).
  static constexpr int kMaxSegments = 1 << 16;
  static constexpr int kTopSizes = 4;
  std::atomic<int> segmenting{0};
  int nseg = 0;
  bool seg_overflow = false;
  uint64_t seg_first[kMaxSegments];
  uint64_t seg_last[kMaxSegments];
  uint64_t seg_call[kMaxSegments];
  bool seg_engine[kMaxSegments];
  uint64_t seg_top_k[kMaxSegments][kTopSizes];
  uint64_t seg_top_size[kMaxSegments][kTopSizes];  // 0 = empty slot
};
inline HostState& Host() {
  static HostState s;
  return s;
}
inline thread_local int t_reentry = 0;

inline void Count(bool segment = false) {
  HostState& h = Host();
  h.nseg = 0;
  h.seg_overflow = false;
  h.segmenting = segment ? 1 : 0;
  h.target = 0;
  h.fired = 0;
  h.seen = 0;
  h.counting = 1;
}
inline void Arm(uint64_t k, int fault) {
  HostState& h = Host();
  h.segmenting = 0;
  h.fired = 0;
  h.seen = 0;
  h.fault = fault;
  h.target = k;
  h.counting = 1;
}
inline uint64_t Disarm() {
  HostState& h = Host();
  h.counting = 0;
  h.segmenting = 0;
  h.target = 0;
  return h.seen.load();
}

// Called on every allocation. Throws when this is the armed k.
inline void KeepIfLarge(int seg, uint64_t k, uint64_t size) {
  HostState& h = Host();
  uint64_t* ks = h.seg_top_k[seg];
  uint64_t* sz = h.seg_top_size[seg];
  if (size <= sz[HostState::kTopSizes - 1]) return;  // ties keep the earlier k
  int i = HostState::kTopSizes - 1;
  while (i > 0 && sz[i - 1] < size) {
    sz[i] = sz[i - 1];
    ks[i] = ks[i - 1];
    --i;
  }
  sz[i] = size;
  ks[i] = k;
}

inline void OnAllocate(std::size_t size) {
  HostState& h = Host();
  if (!h.counting.load(std::memory_order_relaxed) || t_reentry) return;
  const uint64_t n = h.seen.fetch_add(1) + 1;
  if (h.segmenting.load(std::memory_order_relaxed)) {
    const bool eng = semb_test_seam_gpu_occupancy_now() > 0;
    const uint64_t call = semb_test_seam_gpu_call_count();
    if (h.nseg > 0 && h.seg_engine[h.nseg - 1] == eng && h.seg_call[h.nseg - 1] == call) {
      h.seg_last[h.nseg - 1] = n;
      KeepIfLarge(h.nseg - 1, n, size);
    } else if (h.nseg < HostState::kMaxSegments) {
      h.seg_first[h.nseg] = h.seg_last[h.nseg] = n;
      h.seg_engine[h.nseg] = eng;
      h.seg_call[h.nseg] = call;
      for (int j = 0; j < HostState::kTopSizes; ++j) h.seg_top_k[h.nseg][j] = h.seg_top_size[h.nseg][j] = 0;
      KeepIfLarge(h.nseg, n, size);
      ++h.nseg;
    } else {
      h.seg_overflow = true;
    }
  }
  if (n != h.target.load()) return;
  t_reentry = 1;
  h.fired_call_count = semb_test_seam_gpu_call_count();
  h.fired_occupancy = semb_test_seam_gpu_occupancy_now();
  h.fired_size = size;
  h.fired = 1;
  h.counting = 0;  // one fault per arm; the failure paths allocate freely
  t_reentry = 0;
  switch (h.fault.load()) {
    case kLengthError: throw std::length_error("u3 hook: armed length_error");
    case kForeign: throw ForeignFault{};
    default: throw std::bad_alloc();
  }
}

inline void* RawAlloc(std::size_t n) {
  void* p = std::malloc(n ? n : 1);
  if (!p) throw std::bad_alloc();
  return p;
}
inline void* RawAlignedAlloc(std::size_t n, std::size_t align) {
#if defined(_WIN32)
  void* p = _aligned_malloc(n ? n : 1, align);
#else
  const std::size_t rounded = ((n ? n : 1) + align - 1) / align * align;
  void* p = std::aligned_alloc(align, rounded);
#endif
  if (!p) throw std::bad_alloc();
  return p;
}
inline void RawAlignedFree(void* p) {
#if defined(_WIN32)
  _aligned_free(p);
#else
  std::free(p);
#endif
}

#if defined(_WIN32)
// ---- the device hook ------------------------------------------------------
using CreateCommittedResourceFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*, const D3D12_HEAP_PROPERTIES*,
                                                              D3D12_HEAP_FLAGS, const D3D12_RESOURCE_DESC*,
                                                              D3D12_RESOURCE_STATES, const D3D12_CLEAR_VALUE*,
                                                              REFIID, void**);
constexpr int kCreateCommittedResourceSlot = 27;  // IUnknown 0-2, ID3D12Object 3-6, ID3D12Device 7.. (P:4215)
constexpr int kMaxLabels = 8192;

struct DeviceState {
  CreateCommittedResourceFn original = nullptr;
  ID3D12Device* keepalive = nullptr;
  std::atomic<int> counting{0};
  std::atomic<uint64_t> seen{0};
  std::atomic<uint64_t> target{0};
  std::atomic<long> hr{static_cast<long>(E_OUTOFMEMORY)};
  std::atomic<int> fired{0};
  std::atomic<uint64_t> fired_call_count{0};
  std::atomic<uint32_t> fired_occupancy{0};
  int heap_type[kMaxLabels] = {};  // heap type of creation i (1-based index i-1)
  uint64_t call_at[kMaxLabels] = {};  // the running engine-call count at creation i
  bool engine_at[kMaxLabels] = {};    // creation i was made inside an engine call
};
inline DeviceState& Dev() {
  static DeviceState s;
  return s;
}

inline const char* HeapName(int t) {
  switch (t) {
    case D3D12_HEAP_TYPE_DEFAULT: return "DEFAULT";
    case D3D12_HEAP_TYPE_UPLOAD: return "UPLOAD";
    case D3D12_HEAP_TYPE_READBACK: return "READBACK";
    case D3D12_HEAP_TYPE_CUSTOM: return "CUSTOM";
    default: return "?";
  }
}

inline HRESULT STDMETHODCALLTYPE HookedCreateCommittedResource(ID3D12Device* self, const D3D12_HEAP_PROPERTIES* hp,
                                                               D3D12_HEAP_FLAGS flags, const D3D12_RESOURCE_DESC* desc,
                                                               D3D12_RESOURCE_STATES state,
                                                               const D3D12_CLEAR_VALUE* clear, REFIID riid, void** out) {
  DeviceState& d = Dev();
  if (d.counting.load()) {
    const uint64_t n = d.seen.fetch_add(1) + 1;
    if (n <= static_cast<uint64_t>(kMaxLabels)) {
      d.heap_type[n - 1] = hp ? static_cast<int>(hp->Type) : -1;
      d.call_at[n - 1] = semb_test_seam_gpu_call_count();
      d.engine_at[n - 1] = semb_test_seam_gpu_occupancy_now() > 0;
    }
    if (n == d.target.load()) {
      d.fired_call_count = semb_test_seam_gpu_call_count();
      d.fired_occupancy = semb_test_seam_gpu_occupancy_now();
      d.fired = 1;
      d.counting = 0;
      if (out) *out = nullptr;
      return static_cast<HRESULT>(d.hr.load());
    }
  }
  return d.original(self, hp, flags, desc, state, clear, riid, out);
}

// Patches the shared vtable once. Returns false (with no patch) when no D3D12
// device can be created here.
inline bool InstallDeviceHook() {
  DeviceState& d = Dev();
  if (d.original) return true;
  ID3D12Device* dev = nullptr;
  if (FAILED(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device),
                               reinterpret_cast<void**>(&dev))) ||
      !dev) {
    return false;
  }
  void** vtbl = *reinterpret_cast<void***>(dev);
  DWORD old = 0;
  if (!VirtualProtect(&vtbl[kCreateCommittedResourceSlot], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
    dev->Release();
    return false;
  }
  d.original = reinterpret_cast<CreateCommittedResourceFn>(vtbl[kCreateCommittedResourceSlot]);
  vtbl[kCreateCommittedResourceSlot] = reinterpret_cast<void*>(&HookedCreateCommittedResource);
  DWORD ignored = 0;
  VirtualProtect(&vtbl[kCreateCommittedResourceSlot], sizeof(void*), old, &ignored);
  d.keepalive = dev;  // held for the process: the vtable must outlive every device
  return true;
}
inline void DeviceCount() {
  DeviceState& d = Dev();
  d.target = 0;
  d.fired = 0;
  d.seen = 0;
  d.counting = 1;
}
inline void DeviceArm(uint64_t k, HRESULT hr) {
  DeviceState& d = Dev();
  d.fired = 0;
  d.seen = 0;
  d.hr = static_cast<long>(hr);
  d.target = k;
  d.counting = 1;
}
inline uint64_t DeviceDisarm() {
  DeviceState& d = Dev();
  d.counting = 0;
  d.target = 0;
  return d.seen.load();
}
#endif  // _WIN32

}  // namespace u3hook

// ---- the replaced global allocation functions -------------------------------
void* operator new(std::size_t n) {
  u3hook::OnAllocate(n);
  void* p = u3hook::RawAlloc(n);
  u3hook::Host().live.fetch_add(1, std::memory_order_relaxed);
  return p;
}
void* operator new[](std::size_t n) { return ::operator new(n); }
void* operator new(std::size_t n, const std::nothrow_t&) noexcept {
  try {
    return ::operator new(n);
  } catch (...) {
    return nullptr;
  }
}
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept {
  try {
    return ::operator new(n);
  } catch (...) {
    return nullptr;
  }
}
void operator delete(void* p) noexcept {
  if (!p) return;
  u3hook::Host().live.fetch_sub(1, std::memory_order_relaxed);
  std::free(p);
}
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete(void* p, std::size_t) noexcept { ::operator delete(p); }
void operator delete[](void* p, std::size_t) noexcept { ::operator delete(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { ::operator delete(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { ::operator delete(p); }

void* operator new(std::size_t n, std::align_val_t a) {
  u3hook::OnAllocate(n);
  void* p = u3hook::RawAlignedAlloc(n, static_cast<std::size_t>(a));
  u3hook::Host().live.fetch_add(1, std::memory_order_relaxed);
  return p;
}
void* operator new[](std::size_t n, std::align_val_t a) { return ::operator new(n, a); }
void* operator new(std::size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
  try {
    return ::operator new(n, a);
  } catch (...) {
    return nullptr;
  }
}
void* operator new[](std::size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
  try {
    return ::operator new(n, a);
  } catch (...) {
    return nullptr;
  }
}
void operator delete(void* p, std::align_val_t) noexcept {
  if (!p) return;
  u3hook::Host().live.fetch_sub(1, std::memory_order_relaxed);
  u3hook::RawAlignedFree(p);
}
void operator delete[](void* p, std::align_val_t a) noexcept { ::operator delete(p, a); }
void operator delete(void* p, std::size_t, std::align_val_t a) noexcept { ::operator delete(p, a); }
void operator delete[](void* p, std::size_t, std::align_val_t a) noexcept { ::operator delete(p, a); }
void operator delete(void* p, std::align_val_t a, const std::nothrow_t&) noexcept { ::operator delete(p, a); }
void operator delete[](void* p, std::align_val_t a, const std::nothrow_t&) noexcept { ::operator delete(p, a); }

#endif  // U3_ALLOC_HOOK_H
