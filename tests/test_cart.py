# SPDX-License-Identifier: Apache-2.0
"""The SDK 0.2.0 additions for the Bolltridge as a pocket player: PowerState's
new fields, the optional hal subsystems (files, routes, Bluetooth) and their simulator, and the
promise that none of it changes what a board or a caller written before it sees."""
import logging
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import constants  # noqa: E402
from bollardeck.device import hal  # noqa: E402
from bollardeck.device.hal import base, sim  # noqa: E402


class Quiet(unittest.TestCase):
    def setUp(self):
        logging.getLogger("bollardeck.hal").setLevel(logging.ERROR)

    def tearDown(self):
        logging.getLogger("bollardeck.hal").setLevel(logging.NOTSET)


class PowerStateFields(unittest.TestCase):
    def test_the_three_field_form_means_what_it_did(self):
        old = base.PowerState(True, 98.0, 4150)
        self.assertEqual((old.ac_online, old.percent, old.voltage_mv), (True, 98.0, 4150))
        self.assertEqual((old.source, old.charging), ("unknown", None))
        self.assertEqual(old, base.PowerState(ac_online=True, percent=98.0, voltage_mv=4150))
        self.assertEqual(sim.AC_POWER, old)                     # the sim's mains is unchanged

    def test_the_new_fields(self):
        st = base.PowerState(False, 41.0, 7480, source="pack", charging=False)
        self.assertIn(st.source, constants.POWER_SOURCES)
        self.assertEqual(constants.POWER_SOURCES, ("mains", "dock", "usb", "pack", "unknown"))


class Files(unittest.TestCase):
    def test_the_sim_plays_nothing_and_says_what_it_was_asked(self):
        f = sim.NullFiles()
        f.play_file(Path("a.flac"), 12000).stop()
        f.play_file("b.webm")
        self.assertEqual(f.played, [(Path("a.flac"), 12000), (Path("b.webm"), 0)])
        self.assertTrue(f.can_play(Path("x.M4A")))
        self.assertFalse(f.can_play(Path("x.txt")))
        with self.assertRaises(ValueError):
            f.play_file("a.mp3", -1)


class Routes(unittest.TestCase):
    def test_the_default_is_the_machines_own_output(self):
        r = sim.SimRoutes(env={})
        self.assertEqual([x.kind for x in r.available()], ["dock"])
        self.assertEqual(r.current(), "dock")

    def test_routes_from_the_environment_and_unplugging(self):
        r = sim.SimRoutes(env={"BOLLAWAX_SIM_ROUTES": "jack, bt"})
        self.assertEqual([x.kind for x in r.available()], ["jack", "bt"])
        self.assertEqual(r.current(), "bt")
        self.assertEqual(r.select("jack"), "jack")
        with self.assertRaises(ValueError):
            r.select("usb")
        r.unplug("jack")
        self.assertEqual(r.current(), "none")                   # the hal never picks a speaker by itself
        r.plug("usb")
        self.assertEqual(r.current(), "none")                   # plugging does not select: that is the player's rule
        self.assertEqual(r.select("usb"), "usb")

    def test_volume_is_per_route_and_clamped(self):
        r = sim.SimRoutes(["jack", "bt"])
        self.assertEqual(r.set_volume(130), 100)                # bt, the current one
        self.assertEqual(r.set_volume(-5, "jack"), 0)
        self.assertEqual((r.volume("bt"), r.volume("jack")), (100, 0))
        r.select("none")
        self.assertEqual(r.volume(), 0)

    def test_an_unknown_kind_is_left_out(self):
        self.assertEqual([x.kind for x in sim.SimRoutes(["jack", "hdmi", "jack", "none"]).available()], ["jack"])
        self.assertEqual(constants.AUDIO_ROUTES, ("dock", "jack", "bt", "usb", "none"))


class Bluetooth(unittest.TestCase):
    def test_a_headset_found_in_a_window_is_paired_and_connected(self):
        bt = sim.SimBluetooth()
        seen = bt.appear("AA:01", "outside the window", t_ms=0)
        self.assertFalse(seen.paired)
        bt.pair(60, t_ms=1000)
        self.assertEqual(bt.pairing_until(), 61000)
        dev = bt.appear("AA:02", "QC35", t_ms=5000)
        self.assertTrue(dev.paired and dev.connected)
        self.assertIsNone(bt.pairing_until())                   # one window pairs one headset
        bt.disconnect("AA:02")
        self.assertTrue(bt.connect("AA:02"))
        self.assertFalse(bt.connect("AA:01"))                   # seen but never paired
        bt.forget("AA:02")
        self.assertEqual([d.address for d in bt.devices()], ["AA:01"])

    def test_a_window_closes_with_time(self):
        bt = sim.SimBluetooth()
        bt.pair(10, t_ms=0)
        bt.tick(10001)
        self.assertIsNone(bt.pairing_until())
        self.assertFalse(bt.appear("AA:03", t_ms=10002).paired)
        with self.assertRaises(ValueError):
            bt.pair(0)


class BoardsWrittenBefore(Quiet):
    def test_a_module_without_the_new_subsystems_gets_the_sims(self):
        old = types.SimpleNamespace(NAME="old", MAKER_CODE="OLD")     # a board module from before SDK 0.2.0
        b = hal.Board("old", old)
        self.assertIsInstance(b.files(), sim.NullFiles)
        self.assertIsInstance(b.routes(), sim.SimRoutes)
        self.assertIsInstance(b.bluetooth(), sim.SimBluetooth)
        self.assertEqual(set(b.fallbacks), {"files", "routes", "bluetooth"})

    def test_a_module_with_them_is_used(self):
        class Files(sim.NullFiles):
            pass
        mod = types.SimpleNamespace(NAME="new", MAKER_CODE="NEW", FilePlayer=Files,
                                    AudioRoutes=lambda: sim.SimRoutes(["jack"]), Bluetooth=sim.SimBluetooth)
        b = hal.Board("new", mod)
        self.assertIsInstance(b.files(), Files)
        self.assertEqual(b.routes().current(), "jack")
        self.assertEqual(b.fallbacks, {})

    def test_the_sim_board_has_them_without_a_fallback(self):
        b = hal.Board("sim", sim)
        b.files(), b.routes(), b.bluetooth()
        self.assertEqual(b.fallbacks, {})
        self.assertEqual(base.HAL_API, 1)


class Descriptors(unittest.TestCase):
    def test_the_dock_is_still_waiting_for_bollard_v2(self):
        from bollardeck.device import dock
        self.assertFalse(dock.AVAILABLE)

    def test_none_and_plain_are_descriptors_the_cart_makes(self):
        from bollardeck.device import dock
        self.assertEqual(dock.problems(dock.NO_DOCK), [])
        self.assertEqual(dock.problems(dock.PLAIN), [])
        self.assertTrue(dock.problems({"v": 1, "class": "none", "charge_w": 8}))
        self.assertEqual(dock.role_for(dock.NO_DOCK), "pocket")
        self.assertEqual(dock.role_for(None), "pocket")
        self.assertEqual(dock.role_for(dock.PLAIN), "tv")
        self.assertEqual(dock.role_for({"v": 1, "class": "speaker"}), "primary")
        self.assertEqual(dock.role_for({"v": 1, "class": "speaker"}, usb_device=True), "guest")

    def test_the_charge_budget(self):
        from bollardeck.device import dock
        self.assertEqual(dock.charge_budget_w({"v": 1, "class": "speaker", "charge_w": 8}), 8.0)
        self.assertEqual(dock.charge_budget_w({"v": 1, "class": "speaker"}), 5.0)
        self.assertEqual(dock.charge_budget_w(dock.PLAIN), 5.0)
        self.assertEqual(dock.charge_budget_w(dock.NO_DOCK), 0.0)
        self.assertEqual(dock.charge_budget_w({"v": 1, "class": "speaker", "charge_w": True}), 5.0)

    def test_the_cart_descriptor(self):
        from bollardeck.device import cart
        self.assertEqual(cart.problems({"v": 1, "serial": "PB0042-UNOQ-a1b2", "role": "pocket"}), [])
        self.assertTrue(cart.problems({"v": 1, "serial": "PB0042-UNOQ-a1b2", "role": "speaker"}))
        self.assertEqual(cart.ROLES, constants.CART_ROLES)


if __name__ == "__main__":
    unittest.main()
