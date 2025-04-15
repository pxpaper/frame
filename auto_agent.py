#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

AGENT_INTERFACE = "org.bluez.Agent1"
BUS_NAME = "org.bluez"

class AutoAgent(dbus.service.Object):
    def __init__(self, bus, path):
        dbus.service.Object.__init__(self, bus, path)

    # Expect two parameters: an object path and a uint32 for passkey.
    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print("Automatically confirming pairing for device:", device, "with passkey:", passkey)
        return

    # RequestAuthorization expects a single device parameter.
    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print("Automatically authorizing device:", device)
        return

    # Cancel has no parameters.
    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="", out_signature="")
    def Cancel(self):
        print("Pairing request canceled")
        return

    # DisplayPasskey expects three parameters: device, passkey (uint32), and entered (uint16).
    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print("DisplayPasskey called. Device:", device, "Passkey:", passkey, "Entered:", entered)
        return

    # RequestPasskey expects one parameter and returns an unsigned 32-bit integer.
    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print("RequestPasskey called for device:", device)
        return 0  # or return dbus.UInt32(0) if you prefer

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    path = "/com/example/auto_agent"
    agent = AutoAgent(bus, path)
    manager = dbus.Interface(bus.get_object(BUS_NAME, "/org/bluez"),
                             "org.bluez.AgentManager1")
    manager.RegisterAgent(path, "NoInputNoOutput")
    manager.RequestDefaultAgent(path)
    print("Auto agent registered and waiting for pairing requests...")
    loop = GLib.MainLoop()
    loop.run()

if __name__ == '__main__':
    main()
