# vim: set expandtab shiftwidth=4 tabstop=4:
#
# Copyright 2016 Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice (including the next
# paragraph) shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import os
import sys

from enum import IntEnum
from gi.repository import Gio, GLib, GObject


class RatbagErrorCode(IntEnum):
    RATBAG_SUCCESS = 0

    """An error occured on the device. Either the device is not a libratbag
    device or communication with the device failed."""
    RATBAG_ERROR_DEVICE = -1000

    """Insufficient capabilities. This error occurs when a requested change is
    beyond the device's capabilities."""
    RATBAG_ERROR_CAPABILITY = -1001

    """Invalid value or value range. The provided value or value range is
    outside of the legal or supported range."""
    RATBAG_ERROR_VALUE = -1002

    """A low-level system error has occured, e.g. a failure to access files
    that should be there. This error is usually unrecoverable and libratbag will
    print a log message with details about the error."""
    RATBAG_ERROR_SYSTEM = -1003

    """Implementation bug, either in libratbag or in the caller. This error is
    usually unrecoverable and libratbag will print a log message with details
    about the error."""
    RATBAG_ERROR_IMPLEMENTATION = -1004


class RatbagdDBusUnavailable(BaseException):
    """Signals DBus is unavailable or the ratbagd daemon is not available."""
    pass


class _RatbagdDBus(GObject.GObject):
    _dbus = None

    def __init__(self, interface, object_path):
        GObject.GObject.__init__(self)

        if _RatbagdDBus._dbus is None:
            _RatbagdDBus._dbus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            if _RatbagdDBus._dbus is None:
                raise RatbagdDBusUnavailable()

        ratbag1 = "org.freedesktop.ratbag1"
        if os.environ.get('RATBAGCTL_DEVEL'):
            ratbag1 = os.environ['RATBAGCTL_DEVEL']

        if object_path is None:
            object_path = "/" + ratbag1.replace('.', '/')

        self._object_path = object_path

        try:
            self._proxy = Gio.DBusProxy.new_sync(_RatbagdDBus._dbus,
                                                 Gio.DBusProxyFlags.NONE,
                                                 None,
                                                 ratbag1,
                                                 object_path,
                                                 "{}.{}".format(ratbag1, interface),
                                                 None)
        except GLib.Error:
            raise RatbagdDBusUnavailable()

        if self._proxy.get_name_owner() is None:
            raise RatbagdDBusUnavailable()

    def _get_dbus_property(self, property):
        # Retrieves a cached property from the bus, or None.
        p = self._proxy.get_cached_property(property)
        if p is not None:
            return p.unpack()
        return p

    def _dbus_call(self, method, type, *value):
        # Calls a method synchronously on the bus, using the given method name,
        # type signature and values. Returns the returned result, or None.
        val = GLib.Variant("({})".format(type), value)
        try:
            res = self._proxy.call_sync(method, val,
                                        Gio.DBusCallFlags.NO_AUTO_START,
                                        500, None)
            return res.unpack()[0]  # Result is always a tuple
        except GLib.Error as e:
            print(e.message, file=sys.stderr)
            return None

    def __eq__(self, other):
        return other and self._object_path == other._object_path


class Ratbagd(_RatbagdDBus):
    """The ratbagd top-level object. Provides a list of devices available
    through ratbagd; actual interaction with the devices is via the
    RatbagdDevice, RatbagdProfile, RatbagdResolution and RatbagdButton objects.

    Throws RatbagdDBusUnavailable when the DBus service is not available.
    """

    __gsignals__ = {
        "device-added":
            (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, [str]),
        "device-removed":
            (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, [str]),
    }

    def __init__(self):
        _RatbagdDBus.__init__(self, "Manager", None)
        self._proxy.connect("g-signal", self._on_g_signal)

    def _on_g_signal(self, proxy, sender, signal, params):
        params = params.unpack()
        if signal == "DeviceNew":
            self.emit("device-added", params[0])
        elif signal == "DeviceRemoved":
            self.emit("device-removed", params[0])

    @GObject.Property
    def devices(self):
        """A list of RatbagdDevice objects supported by ratbagd."""
        devices = []
        result = self._get_dbus_property("Devices")
        if result is not None:
            devices = [RatbagdDevice(objpath) for objpath in result]
        return devices

    @GObject.Property
    def themes(self):
        """A list of theme names. The theme 'default' is guaranteed to be
        available."""
        return self._get_dbus_property("Themes")


class RatbagdDevice(_RatbagdDBus):
    """Represents a ratbagd device."""

    CAP_NONE = 0
    CAP_QUERY_CONFIGURATION = 1
    CAP_RESOLUTION = 100
    CAP_SWITCHABLE_RESOLUTION = 101
    CAP_PROFILE = 200
    CAP_SWITCHABLE_PROFILE = 201
    CAP_DISABLE_PROFILE = 202
    CAP_DEFAULT_PROFILE = 203
    CAP_BUTTON = 300
    CAP_BUTTON_KEY = 301
    CAP_BUTTON_MACROS = 302
    CAP_LED = 400

    def __init__(self, object_path):
        _RatbagdDBus.__init__(self, "Device", object_path)

    @GObject.Property
    def id(self):
        """The unique identifier of this device."""
        return self._get_dbus_property("Id")

    @GObject.Property
    def capabilities(self):
        """The capabilities of this device as an array. Capabilities not
        present on the device are not in the list. Thus use e.g.

        if RatbagdDevice.CAP_SWITCHABLE_RESOLUTION is in device.capabilities:
            do something
        """
        return self._get_dbus_property("Capabilities")

    @GObject.Property
    def name(self):
        """The device name, usually provided by the kernel."""
        return self._get_dbus_property("Name")

    @GObject.Property
    def profiles(self):
        """A list of RatbagdProfile objects provided by this device."""
        profiles = []
        result = self._get_dbus_property("Profiles")
        if result is not None:
            profiles = [RatbagdProfile(objpath) for objpath in result]
        return profiles

    @GObject.Property
    def active_profile(self):
        """The currently active profile. This function returns a RatbagdProfile
        or None if no active profile was found."""
        profiles = self.profiles
        active_index = self._get_dbus_property("ActiveProfile")
        return profiles[active_index] if len(profiles) > active_index else None

    def get_svg(self, theme):
        """Gets the full path to the SVG for the given theme, or the empty
        string if none is available.

        The theme must be one of org.freedesktop.ratbag1.Manager.Themes. The
        theme 'default' is guaranteed to be available.

        @param theme The theme from which to retrieve the SVG, as str
        """
        return self._dbus_call("GetSvg", "s", theme)

    def get_profile_by_index(self, index):
        """Returns the profile found at the given index, or None if no profile
        was found.

        @param index The index to find the profile at, as int
        """
        return self._dbus_call("GetProfileByIndex", "u", index)

    def commit(self):
        """Commits all changes made to the device."""
        return self._dbus_call("Commit", "")


class RatbagdProfile(_RatbagdDBus):
    """Represents a ratbagd profile."""

    __gsignals__ = {
        "active-profile-changed":
            (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, [int]),
    }

    def __init__(self, object_path):
        _RatbagdDBus.__init__(self, "Profile", object_path)
        self._proxy.connect("g-signal", self._on_g_signal)

    def _on_g_signal(self, proxy, sender, signal, params):
        params = params.unpack()
        if signal == "ActiveProfileChanged":
            self.emit("active-profile-changed", params[0])

    @GObject.Property
    def index(self):
        """The index of this profile."""
        return self._get_dbus_property("Index")

    @GObject.Property
    def resolutions(self):
        """A list of RatbagdResolution objects with this profile's resolutions.
        """
        resolutions = []
        result = self._get_dbus_property("Resolutions")
        if result is not None:
            resolutions = [RatbagdResolution(objpath) for objpath in result]
        return resolutions

    @GObject.Property
    def buttons(self):
        """A list of RatbagdButton objects with this profile's button mappings.
        Note that the list of buttons differs between profiles but the number
        of buttons is identical across profiles."""
        buttons = []
        result = self._get_dbus_property("Buttons")
        if result is not None:
            buttons = [RatbagdButton(objpath) for objpath in result]
        return buttons

    @GObject.Property
    def leds(self):
        """A list of RatbagdLed objects with this profile's leds."""
        leds = []
        result = self._get_dbus_property("Leds")
        if result is not None:
            leds = [RatbagdLed(objpath) for objpath in result]
        return leds

    @GObject.Property
    def active_resolution(self):
        """The currently active resolution. This function returns a
        RatbagdResolution object or None."""
        resolutions = self.resolutions
        active_index = self._get_dbus_property("ActiveResolution")
        return resolutions[active_index] if len(resolutions) > active_index else None

    @GObject.Property
    def default_resolution(self):
        """The default resolution. This function returns a RatbagdResolution
        object or None."""
        resolutions = self.resolutions
        default_index = self._get_dbus_property("DefaultResolution")
        return resolutions[default_index] if len(resolutions) > default_index else None

    def set_active(self):
        """Set this profile to be the active profile."""
        return self._dbus_call("SetActive", "")

    def get_resolution_by_index(self, index):
        """Returns the resolution found at the given index. This function
        returns a RatbagdResolution or None if no resolution was found."""
        return self._dbus_call("GetResolutionByIndex", "u", index)


class RatbagdResolution(_RatbagdDBus):
    """Represents a ratbagd resolution."""

    CAP_INDIVIDUAL_REPORT_RATE = 1
    CAP_SEPARATE_XY_RESOLUTION = 2

    __gsignals__ = {
        "active-resolution-changed":
            (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, [int]),
        "default-resolution-changed":
            (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, [int]),
    }

    def __init__(self, object_path):
        _RatbagdDBus.__init__(self, "Resolution", object_path)
        self._proxy.connect("g-signal", self._on_g_signal)

    def _on_g_signal(self, proxy, sender, signal, params):
        params = params.unpack()
        if signal == "ActiveResolutionChanged":
            self.emit("active-resolution-changed", params[0])
        elif signal == "DefaultResolutionChanged":
            self.emit("default-resolution-changed", params[0])

    @GObject.Property
    def index(self):
        """The index of this resolution."""
        return self._get_dbus_property("Index")

    @GObject.Property
    def capabilities(self):
        """The capabilities of this resolution as a list. Capabilities not
        present on the resolution are not in the list. Thus use e.g.

        if RatbagdResolution.CAP_SEPARATE_XY_RESOLUTION is in resolution.capabilities:
            do something
        """
        return self._get_dbus_property("Capabilities")

    @GObject.Property
    def resolution(self):
        """The tuple (xres, yres) with each resolution in DPI."""
        return self._get_dbus_property("XResolution"), self._get_dbus_property("YResolution")

    @resolution.setter
    def resolution(self, res):
        """Set the x- and y-resolution using the given (xres, yres) tuple.

        @param res The new resolution, as (int, int)
        """
        return self._dbus_call("SetResolution", "uu", *res)

    @GObject.Property
    def report_rate(self):
        """The report rate in Hz."""
        return self._get_dbus_property("ReportRate")

    @GObject.Property
    def maximum(self):
        """The maximum possible resolution."""
        return self._get_dbus_property("Maximum")

    @GObject.Property
    def minimum(self):
        """The minimum possible resolution."""
        return self._get_dbus_property("Minimum")

    @report_rate.setter
    def report_rate(self, rate):
        """Set the report rate in Hz.

        @param rate The new report rate, as int
        """
        return self._dbus_call("SetReportRate", "u", rate)

    def set_default(self):
        """Set this resolution to be the default."""
        return self._dbus_call("SetDefault", "")


class RatbagdButton(_RatbagdDBus):
    """Represents a ratbagd button."""

    def __init__(self, object_path):
        _RatbagdDBus.__init__(self, "Button", object_path)

    @GObject.Property
    def index(self):
        """The index of this button."""
        return self._get_dbus_property("Index")

    @GObject.Property
    def type(self):
        """A string describing this button's type."""
        return self._get_dbus_property("Type")

    @GObject.Property
    def mapping(self):
        """An integer of the current button mapping, if mapping to a button."""
        return self._get_dbus_property("ButtonMapping")

    @mapping.setter
    def mapping(self, button):
        """Set the button mapping to the given button.

        @param button The button to map to, as int
        """
        return self._dbus_call("SetButtonMapping", "u", button)

    @GObject.Property
    def special(self):
        """A string of the current special mapping, if mapped to special."""
        return self._get_dbus_property("SpecialMapping")

    @special.setter
    def special(self, special):
        """Set the button mapping to the given special entry.

        @param special The special entry, as str
        """
        return self._dbus_call("SetSpecialMapping", "s", special)

    @GObject.Property
    def key(self):
        """A list of integers, the first being the keycode and the other
        entries, if any, are modifiers (if mapped to key)."""
        return self._get_dbus_property("KeyMapping")

    @key.setter
    def key(self, keys):
        """Set the key mapping.

        @param keys A list of integers, the first being the keycode and the rest
                    modifiers.
        """
        return self._dbus_call("SetKeyMapping", "au", keys)

    @GObject.Property
    def action_type(self):
        """A string describing the action type of the button. One of "none",
        "button", "key", "special", "macro" or "unknown". This decides which
        *Mapping property has a value.
        """
        return self._get_dbus_property("ActionType")

    @GObject.Property
    def action_types(self):
        """An array of possible values for ActionType."""
        return self._get_dbus_property("ActionTypes")

    def disable(self):
        """Disables this button."""
        return self._dbus_call("Disable", "")


class RatbagdLed(_RatbagdDBus):
    """Represents a ratbagd led."""

    MODE_OFF = 0
    MODE_ON = 1
    MODE_CYCLE = 2
    MODE_BREATHING = 3

    def __init__(self, object_path):
        _RatbagdDBus.__init__(self, "Led", object_path)

    @GObject.Property
    def index(self):
        """The index of this led."""
        return self._get_dbus_property("Index")

    @GObject.Property
    def mode(self):
        """This led's mode, one of MODE_OFF, MODE_ON, MODE_CYCLE and
        MODE_BREATHING."""
        return self._get_dbus_property("Mode")

    @mode.setter
    def mode(self, mode):
        """Set the led's mode to the given mode.

        @param mode The new mode, as one of MODE_OFF, MODE_ON, MODE_CYCLE and
                    MODE_BREATHING.
        """
        return self._dbus_call("SetMode", "u", mode)

    @GObject.Property
    def type(self):
        """A string describing this led's type."""
        return self._get_dbus_property("Type")

    @GObject.Property
    def color(self):
        """An integer triple of the current LED color."""
        return self._get_dbus_property("Color")

    @color.setter
    def color(self, color):
        """Set the led color to the given color.

        @param color An RGB color, as an integer triplet with values 0-255.
        """
        return self._dbus_call("SetColor", "(uuu)", color)

    @GObject.Property
    def effect_rate(self):
        """The LED's effect rate in Hz, values range from 100 to 20000."""
        return self._get_dbus_property("EffectRate")

    @effect_rate.setter
    def effect_rate(self, effect_rate):
        """Set the effect rate in Hz. Allowed values range from 100 to 20000.

        @param effect_rate The new effect rate, as int
        """
        return self._dbus_call("SetEffectRate", "u", effect_rate)

    @GObject.Property
    def brightness(self):
        """The LED's brightness, values range from 0 to 255."""
        return self._get_dbus_property("Brightness")

    @brightness.setter
    def brightness(self, brightness):
        """Set the brightness. Allowed values range from 0 to 255.

        @param brightness The new brightness, as int
        """
        return self._dbus_call("SetBrightness", "u", brightness)
