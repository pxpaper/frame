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

    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="o", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print("Automatically confirming pairing for device:", device)
        return

    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print("Automatically authorizing device:", device)
        return

    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="", out_signature="")
    def Cancel(self):
        print("Pairing request canceled")
        return

    # The following methods are implemented with default behavior.
    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="os", out_signature="")
    def DisplayPasskey(self, device, passkey):
        # No display on our headless Pi.
        print("DisplayPasskey called. Device:", device, "Passkey:", passkey)
        return

    @dbus.service.method(AGENT_INTERFACE,
                         in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        # For just works, we don't request a passkey.
        print("RequestPasskey called for device:", device)
        return 0

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
