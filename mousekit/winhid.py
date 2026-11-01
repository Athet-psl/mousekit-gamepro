"""HID devices on Windows through hid.dll and SetupAPI (ctypes, no extra packages).

Windows splits a USB HID interface into one device per top-level collection,
each with its own path: the GM500W's vendor channel, consumer keys and system
keys are separate devices here, where Linux has one hidraw node per interface.
Feature reports must be exactly the collection's FeatureReportByteLength long,
so shorter packets are padded with zeros (as the vendor app does).
"""

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass

hid = ctypes.WinDLL("hid.dll", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
DIGCF_PRESENT = 0x2
DIGCF_DEVICEINTERFACE = 0x10
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
HIDP_STATUS_SUCCESS = 0x00110000
HIDP_INPUT, HIDP_OUTPUT, HIDP_FEATURE = 0, 1, 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT), ("ProductID", wintypes.USHORT),
                ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT), ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT), ("Reserved", wintypes.USHORT * 17),
                ("NumberLinkCollectionNodes", wintypes.USHORT),
                ("NumberInputButtonCaps", wintypes.USHORT), ("NumberInputValueCaps", wintypes.USHORT),
                ("NumberInputDataIndices", wintypes.USHORT),
                ("NumberOutputButtonCaps", wintypes.USHORT), ("NumberOutputValueCaps", wintypes.USHORT),
                ("NumberOutputDataIndices", wintypes.USHORT),
                ("NumberFeatureButtonCaps", wintypes.USHORT), ("NumberFeatureValueCaps", wintypes.USHORT),
                ("NumberFeatureDataIndices", wintypes.USHORT)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    # Only the fields Mousekit reads are named; the union at the end is kept as raw bytes.
    _fields_ = [("UsagePage", wintypes.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", wintypes.USHORT), ("LinkCollection", wintypes.USHORT),
                ("LinkUsage", wintypes.USHORT), ("LinkUsagePage", wintypes.USHORT),
                ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte),
                ("HasNull", ctypes.c_ubyte), ("Reserved", ctypes.c_ubyte), ("BitSize", wintypes.USHORT),
                ("ReportCount", wintypes.USHORT), ("Reserved2", wintypes.USHORT * 5),
                ("UnitsExp", wintypes.ULONG), ("Units", wintypes.ULONG),
                ("LogicalMin", wintypes.LONG), ("LogicalMax", wintypes.LONG),
                ("PhysicalMin", wintypes.LONG), ("PhysicalMax", wintypes.LONG),
                ("Union", ctypes.c_ubyte * 16)]


class HIDP_BUTTON_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wintypes.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", wintypes.USHORT), ("LinkCollection", wintypes.USHORT),
                ("LinkUsage", wintypes.USHORT), ("LinkUsagePage", wintypes.USHORT),
                ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte),
                ("ReportCount", wintypes.USHORT), ("Reserved2", wintypes.USHORT),
                ("Reserved", wintypes.ULONG * 9), ("Union", ctypes.c_ubyte * 16)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


GUID_HID = GUID()
hid.HidD_GetHidGuid(ctypes.byref(GUID_HID))

setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                 wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                              ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
for _name in ("HidD_SetFeature", "HidD_GetFeature", "HidD_GetInputReport"):
    getattr(hid, _name).argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    getattr(hid, _name).restype = wintypes.BOOLEAN
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.restype = wintypes.BOOLEAN
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = wintypes.LONG
hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetValueCaps.restype = wintypes.LONG
hid.HidP_GetButtonCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetButtonCaps.restype = wintypes.LONG


@dataclass
class Collection:
    """One HID top-level collection: what Windows exposes as a device path."""

    path: str
    vendor: int
    product: int
    version: int
    usage_page: int
    usage: int
    input_size: int
    output_size: int
    feature_size: int
    report_ids: dict    # "input"/"output"/"feature" -> sorted report ids
    product_name: str = ""
    buttons: int = 0    # highest button usage (page 9) among the input reports

    @property
    def key(self):
        return f"{self.vendor:04x}:{self.product:04x}"

    @property
    def interface(self):
        """USB interface number from the path ("...&mi_01&col03..."), or None."""
        match = re.search(r"&mi_([0-9a-f]{2})", self.path, re.IGNORECASE)
        return int(match.group(1), 16) if match else None

    @property
    def number(self):
        """Top-level collection number from the path, or None when the interface has just one."""
        match = re.search(r"&col([0-9a-f]{2})", self.path, re.IGNORECASE)
        return int(match.group(1), 16) if match else None


def _open(path, access=GENERIC_READ | GENERIC_WRITE, flags=0):
    handle = kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
    if handle in (None, INVALID_HANDLE_VALUE):
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def device_paths():
    """Device paths of every HID collection present."""
    info = setupapi.SetupDiGetClassDevsW(ctypes.byref(GUID_HID), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if info in (None, INVALID_HANDLE_VALUE):
        return []
    paths = []
    try:
        index = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA(cbSize=ctypes.sizeof(SP_DEVICE_INTERFACE_DATA))
            if not setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(GUID_HID), index, ctypes.byref(data)):
                break
            index += 1
            needed = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), None, 0, ctypes.byref(needed), None)
            buf = ctypes.create_string_buffer(needed.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W: DWORD cbSize, then the path. cbSize is 8 on 64-bit Python, 6 on 32.
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), buf, needed, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


def _input_buttons(preparsed, caps):
    if not caps.NumberInputButtonCaps:
        return 0
    count = wintypes.USHORT(caps.NumberInputButtonCaps)
    array = (HIDP_BUTTON_CAPS * count.value)()
    if hid.HidP_GetButtonCaps(HIDP_INPUT, array, ctypes.byref(count), preparsed) != HIDP_STATUS_SUCCESS:
        return 0
    highest = 0
    for i in range(count.value):
        if array[i].UsagePage == 0x09:
            union = bytes(array[i].Union)  # Range: UsageMin, UsageMax; NotRange: Usage
            usage = int.from_bytes(union[2:4] if array[i].IsRange else union[0:2], "little")
            highest = max(highest, usage)
    return highest


def _report_ids(preparsed, caps):
    ids = {}
    for kind, report, n_buttons, n_values in (
            ("input", HIDP_INPUT, caps.NumberInputButtonCaps, caps.NumberInputValueCaps),
            ("output", HIDP_OUTPUT, caps.NumberOutputButtonCaps, caps.NumberOutputValueCaps),
            ("feature", HIDP_FEATURE, caps.NumberFeatureButtonCaps, caps.NumberFeatureValueCaps)):
        found = set()
        if n_values:
            count = wintypes.USHORT(n_values)
            array = (HIDP_VALUE_CAPS * n_values)()
            if hid.HidP_GetValueCaps(report, array, ctypes.byref(count), preparsed) == HIDP_STATUS_SUCCESS:
                found |= {array[i].ReportID for i in range(count.value)}
        if n_buttons:
            count = wintypes.USHORT(n_buttons)
            array = (HIDP_BUTTON_CAPS * n_buttons)()
            if hid.HidP_GetButtonCaps(report, array, ctypes.byref(count), preparsed) == HIDP_STATUS_SUCCESS:
                found |= {array[i].ReportID for i in range(count.value)}
        ids[kind] = sorted(found)
    return ids


def describe(path):
    """The Collection at `path`, or None if it can't be queried.

    Opened with no access rights: that works even for the mouse and keyboard
    collections Windows keeps for itself.
    """
    try:
        handle = _open(path, access=0)
    except OSError:
        return None
    try:
        attrs = HIDD_ATTRIBUTES(Size=ctypes.sizeof(HIDD_ATTRIBUTES))
        if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
            return None
        preparsed = ctypes.c_void_p()
        if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            return None
        try:
            caps = HIDP_CAPS()
            if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                return None
            ids = _report_ids(preparsed, caps)
            buttons = _input_buttons(preparsed, caps)
        finally:
            hid.HidD_FreePreparsedData(preparsed)
        name = ctypes.create_unicode_buffer(128)
        product = name.value if hid.HidD_GetProductString(handle, name, ctypes.sizeof(name)) else ""
        return Collection(path, attrs.VendorID, attrs.ProductID, attrs.VersionNumber, caps.UsagePage, caps.Usage,
                          caps.InputReportByteLength, caps.OutputReportByteLength, caps.FeatureReportByteLength,
                          ids, product, buttons)
    finally:
        kernel32.CloseHandle(handle)


def collections(key=None):
    """Every HID collection present, or only those of USB id "vvvv:pppp"."""
    found = []
    wanted = f"vid_{key[:4]}&pid_{key[5:]}" if key else None
    for path in device_paths():
        if wanted and wanted not in path.lower():
            continue
        coll = describe(path)
        if coll and (key is None or coll.key == key):
            found.append(coll)
    return sorted(found, key=lambda c: c.path.lower())


class Device:
    """An open HID collection: feature reports both ways, and input reports read with a timeout."""

    def __init__(self, path):
        coll = describe(path)
        if coll is None:
            raise OSError(f"no such HID device: {path}")
        self.path = path
        self.feature_size = coll.feature_size
        self.input_size = coll.input_size
        self.handle = _open(path, flags=FILE_FLAG_OVERLAPPED)
        self._event = kernel32.CreateEventW(None, True, False, None)
        self._overlapped = None
        self._buffer = None

    def set_feature(self, data):
        buf = bytes(data).ljust(self.feature_size, b"\0") if self.feature_size else bytes(data)
        if not hid.HidD_SetFeature(self.handle, buf, len(buf)):
            raise ctypes.WinError(ctypes.get_last_error())
        return len(data)

    def get_feature(self, report_id, size):
        buf = ctypes.create_string_buffer(max(size, self.feature_size))
        buf[0] = report_id
        if not hid.HidD_GetFeature(self.handle, buf, len(buf)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw[:size]

    def read(self, timeout=0.0):
        """One input report (report id first), or None if none arrives within `timeout` seconds.

        A read left pending by a timeout carries over to the next call, so no report is lost.
        """
        if not self.input_size:
            return None
        if self._overlapped is None:
            kernel32.ResetEvent(self._event)
            self._overlapped = OVERLAPPED(hEvent=self._event)
            self._buffer = ctypes.create_string_buffer(self.input_size)
            if not kernel32.ReadFile(self.handle, self._buffer, self.input_size, None, ctypes.byref(self._overlapped)):
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    self._overlapped = None
                    raise ctypes.WinError(error)
        result = kernel32.WaitForSingleObject(self._event, max(0, int(timeout * 1000)))
        if result == WAIT_TIMEOUT:
            return None
        done = wintypes.DWORD()
        overlapped, self._overlapped = self._overlapped, None
        if not kernel32.GetOverlappedResult(self.handle, ctypes.byref(overlapped), ctypes.byref(done), False):
            raise ctypes.WinError(ctypes.get_last_error())
        return self._buffer.raw[:done.value]

    def close(self):
        if self.handle is None:
            return
        overlapped, self._overlapped = self._overlapped, None
        if overlapped is not None:  # a read still pending: cancel it before its buffer goes away
            kernel32.CancelIoEx(self.handle, ctypes.byref(overlapped))
            done = wintypes.DWORD()
            kernel32.GetOverlappedResult(self.handle, ctypes.byref(overlapped), ctypes.byref(done), True)
        kernel32.CloseHandle(self.handle)
        kernel32.CloseHandle(self._event)
        self.handle = None


kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
