#! /usr/bin/env python3

# from gi.repository import Gtk, GdkPixbuf, GObject, Pango, Gdk, GLib
from gi.repository import Gtk, GObject, GLib
from os.path import join, abspath, dirname, basename, \
                    splitext, exists, expanduser, isdir
from utils import ExecuteThreadedCommands, getoutput, \
                  shell_exec, getPackageVersion
import os
from glob import glob
from datetime import datetime
from dialogs import MessageDialog, ErrorDialog, WarningDialog, \
                    SelectFileDialog, QuestionDialog
from combobox import ComboBoxHandler
from treeview import TreeViewHandler
from queue import Queue
from logger import Logger

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain('usb-creator')

# Need to initiate threads for Gtk
GObject.threads_init()


#class for the main window
class USBCreator(object):

    def __init__(self):

        # Load window and widgets
        self.scriptName = basename(__file__)
        self.scriptDir = abspath(dirname(__file__))
        self.mediaDir = join(self.scriptDir, '../../share/usb-creator')
        self.builder = Gtk.Builder()
        self.builder.add_from_file(join(self.mediaDir, 'usb-creator.glade'))

        # Main window objects
        go = self.builder.get_object
        self.window = go("usb-creator")
        self.lblDevice = go("lblDevice")
        self.lblIso = go("lblIso")
        self.lblAvailable = go("lblAvailable")
        self.lblRequired = go("lblRequired")
        self.cmbDevice = go("cmbDevice")
        self.cmbDeviceHandler = ComboBoxHandler(self.cmbDevice)
        self.txtIso = go("txtIso")
        self.btnRefresh = go("btnRefresh")
        self.btnUnmount = go("btnUnmount")
        self.btnBrowseIso = go("btnBrowseIso")
        self.btnClear = go("btnClear")
        self.chkFormatDevice = go("chkFormatDevice")
        self.chkRepairDevice = go("chkRepairDevice")
        self.btnExecute = go("btnExecute")
        self.lblUsb = go("lblUsb")
        self.tvUsbIsos = go("tvUsbIsos")
        self.btnDelete = go("btnDelete")
        self.pbUsbCreator = go("pbUsbCreator")
        self.statusbar = go("statusbar")

        # Translations
        self.window.set_title(_("USB Creator"))
        self.lblDevice.set_label(_("Device"))
        self.lblUsb.set_label(_("USB"))
        self.available_text = _("Available")
        self.required_text = _("Required")
        self.chkFormatDevice.set_label(_("Format device"))
        self.chkFormatDevice.set_tooltip_text(_("Warning: all data will be lost"))
        self.chkRepairDevice.set_label(_("Repair device"))
        self.chkRepairDevice.set_tooltip_text(_("Tries to repair an unbootable USB"))
        self.btnExecute.set_label("_{}".format(_("Execute")))
        self.lblIso.set_label(_("ISO"))
        self.btnDelete.set_label("_{}".format(_("Delete")))
        self.btnRefresh.set_tooltip_text(_("Refresh device list"))
        self.btnUnmount.set_tooltip_text(_("Unmount device"))
        self.btnBrowseIso.set_tooltip_text(_("Browse for ISO file"))
        self.btnClear.set_tooltip_text(_("Clear the ISO field"))

        # Log lines to show: check string, percent done (0=pulse, appends last word in log line), show line (translatable)
        self.log_lines = []
        self.log_lines.append(["partitioning usb", 5, _("Partitioning USB...")])
        self.log_lines.append(["searching for bad blocks", 0, _("Searching for bad block")])
        self.log_lines.append(["installing", 15, _("Installing Grub...")])
        self.log_lines.append(["rsync", 25, _("Start copying ISO...")])
        self.log_lines.append(["left to copy", 0, _("kB left to copy:")])
        self.log_lines.append(["check md5sum", 85, _("Check md5sum of ISO...")])

        # Initiate variables
        self.devices = []
        self.device = {}
        self.device['path'] = ''
        self.device['size'] = 0
        self.device['has_partition'] = False
        self.device['mount'] = ''
        self.device['available'] = 0
        self.device['new_iso'] = ''
        self.device['new_iso_required'] = 0
        self.logos = self.get_logos()
        self.queue = Queue(-1)
        self.threads = {}
        log = getoutput("cat /usr/bin/usb-creator | grep 'LOG=' | cut -d'=' -f 2")
        self.log_file = log[0]
        self.log = Logger(self.log_file, addLogTime=False, maxSizeKB=5120)
        self.tvUsbIsosHandler = TreeViewHandler(self.tvUsbIsos)

        self.lblAvailable.set_label('')
        self.lblRequired.set_label('')

        # Connect builder signals and show window
        self.builder.connect_signals(self)
        self.window.show_all()

        # Get attached devices
        self.on_btnRefresh_clicked()

        # Init log
        init_log = "\n===============================================\n" \
                   "Start USB Creator: {}\n" \
                   "===============================================".format(datetime.now())
        self.log.write(init_log)

        # Version information
        self.version_text = _("Version")
        self.pck_version = getPackageVersion('usb-creator')
        self.set_statusbar_message("{}: {}".format(self.version_text, self.pck_version))

    # ===============================================
    # Main window functions
    # ===============================================

    def on_btnExecute_clicked(self, widget):
        if exists(self.device["path"]):
            arguments = []
            arguments.append("-d {}".format(self.device["path"]))
            clear = self.chkFormatDevice.get_active()
            repair = self.chkRepairDevice.get_active()
            iso = self.device["new_iso"]
            iso_path = self.txtIso.get_text().strip()

            # ISO path does not exist
            if iso != iso_path:
                msg = _("Cannot add ISO from path: {}.\n"
                        "Please, remove the ISO path or browse for an existing ISO.")
                WarningDialog(self.btnExecute.get_label(), msg.format(iso_path))
                return True

            # Check if there is enough space
            available = self.device["available"]
            if self.chkFormatDevice.get_active():
                available = self.device["size"]
            if available - self.device["new_iso_required"] < 0:
                msg = _("There is not enough space available on the pen drive.\n"
                        "Please, remove unneeded files before continuing.")
                WarningDialog(self.btnExecute.get_label(), msg)
                return True

            if clear:
                arguments.append("-f")
                arguments.append("-b")
            if repair:
                arguments.append("-r")
                arguments.append("-b")
                arguments.append("-g")
            if exists(iso):
                arguments.append("-i \"{}\"".format(iso))
                arguments.append("-m")

            cmd = "usb-creator {}".format(" ".join(arguments))
            self.log.write("Execute command: {}".format(cmd))
            self.exec_command(cmd)

    def on_btnDelete_clicked(self, widget):
        selected_isos = self.tvUsbIsosHandler.getToggledValues(toggleColNr=0, valueColNr=2)
        if selected_isos:
            msg =  _("Are you sure you want to remove the selected ISO from the device?")
            answer = QuestionDialog(self.btnDelete.get_label(), msg)
            if answer:
                for iso in selected_isos:
                    iso_path = join(self.device["mount"], iso)
                    if exists(iso_path):
                        os.remove(iso_path)
                        self.log.write("Remove ISO: {}".format(iso_path))
                self.on_cmbDevice_changed()
                self.fill_treeview_usbcreator(self.device["mount"])

    def on_btnBrowseIso_clicked(self, widget):
        file_filter = Gtk.FileFilter()
        file_filter.set_name("ISO")
        file_filter.add_mime_type("application/x-cd-image")
        file_filter.add_pattern("*.iso")

        start_dir = dirname(self.txtIso.get_text())
        if not exists(start_dir):
            start_dir = expanduser("~")

        iso = SelectFileDialog(title=_('Select ISO'), start_directory=start_dir, gtkFileFilter=file_filter).show()
        if iso is not None:
            self.log.write("Add ISO: {}".format(iso))
            self.txtIso.set_text(iso)

    def on_btnClear_clicked(self, widget):
        self.txtIso.set_text('')

    def on_txtIso_changed(self, widget):
        iso_path = self.txtIso.get_text()
        if exists(iso_path):
            if isdir(iso_path):
                isos = glob(join(iso_path, '*.iso'))
                required = 0
                for iso in isos:
                    # Check if these ISOs overwrite current USB ISOs
                    check_usb_iso = join(self.device["mount"], basename(iso))
                    check_usb_iso_size = 0
                    if exists(check_usb_iso):
                        check_usb_iso_size = self.get_iso_size(check_usb_iso)
                    required += (self.get_iso_size(iso) - check_usb_iso_size)
                self.lblRequired.set_label("{}: {} MB".format(self.required_text, int(required / 1024)))
                # Save the info
                if required > 0:
                    self.device['new_iso'] = iso_path
                    self.device['new_iso_required'] = required
                    self.log.write("New ISO directory: {}, {}".format(iso_path, required))
                else:
                    self.device['new_iso'] = ''
                    self.device['new_iso_required'] = 0
                    self.log.write("New ISO directory does not contain ISOs: {}".format(iso_path))
            else:
                # Check if this ISO overwrites current USB ISO
                check_usb_iso = join(self.device["mount"], basename(iso_path))
                check_usb_iso_size = 0
                if exists(check_usb_iso):
                    check_usb_iso_size = self.get_iso_size(check_usb_iso)
                required = (self.get_iso_size(iso_path) - check_usb_iso_size)
                self.lblRequired.set_label("{}: {} MB".format(self.required_text, int(required / 1024)))
                # Save the info
                self.device['new_iso'] = iso_path
                self.device['new_iso_required'] = required
                self.log.write("New ISO: {}, {}".format(iso_path, required))
        else:
            self.device['new_iso'] = ''
            self.device['new_iso_required'] = 0
            self.lblRequired.set_text('')

    def on_btnRefresh_clicked(self, widget=None):
        self.devices = self.get_devices()
        self.cmbDeviceHandler.fillComboBox(self.devices, 0)

    def on_btnUnmount_clicked(self, widget):
        unmount_text = _("Unmount")
        device = self.device["path"]
        self.unmount_device(device)
        self.on_btnRefresh_clicked()
        if device in self.devices:
            msg = _("Could not unmount the device.\n"
                    "Please unmount the device manually.")
        else:
            msg = _("You can now safely remove the device.")
        MessageDialog(unmount_text, msg)

    def on_cmbDevice_changed(self, widget=None):
        device = self.cmbDeviceHandler.getValue()
        if device is not None:
            mount = ''
            size = 0
            available = 0

            # Get the size of the USB
            usb_size = getoutput("env LANG=C udisks --show-info {} | grep size".format(device))
            if usb_size:
                # udisks returns bytes, while df returns kbs
                size = int(int(usb_size[0].split(":")[1].strip()) / 1024)

            # Get free size on USB
            has_partition = self.device_has_partition(device)
            if has_partition:
                mount = self.get_device_mount(device)
                free_size = getoutput("df --output=avail {}1 | awk 'NR==2'".format(device))
                if free_size:
                    available = int(free_size[0])
                self.chkFormatDevice.set_sensitive(True)
                self.chkFormatDevice.set_active(False)
            else:
                available = size
                self.chkFormatDevice.set_active(True)
                self.chkFormatDevice.set_sensitive(False)

            self.chkRepairDevice.set_active(False)
            self.fill_treeview_usbcreator(mount)
            self.lblAvailable.set_label("{}: {} MB".format(self.available_text, int(available / 1024)))

            # Save the info
            self.device['path'] = device
            self.device['size'] = size
            self.device['has_partition'] = has_partition
            self.device['mount'] = mount
            self.device['available'] = available
            self.log.write("Selected device info: {}".format(self.device))
        else:
            self.fill_treeview_usbcreator()
            self.lblAvailable.set_label('')
            self.lblRequired.set_label('')
            self.txtIso.set_text('')
            self.device['path'] = ''
            self.device['size'] = 0
            self.device['has_partition'] = False
            self.device['mount'] = ''
            self.device['available'] = 0
            self.device["new_iso"] = ''
            self.device["new_iso_required"] = 0

    def on_chkFormatDevice_toggled(self, widget):
        # Recalculate available space
        available = self.device["available"]
        if widget.get_active():
            available = self.device["size"]
        self.lblAvailable.set_label("{}: {} MB".format(self.available_text, int(available / 1024)))

    def fill_treeview_usbcreator(self, mount=''):
        isos_list = []
        # columns: checkbox, image (logo), device, driver
        column_types = ['bool', 'GdkPixbuf.Pixbuf', 'str', 'str']

        if exists(mount):
            isos = glob(join(mount, '*.iso'))
            for iso in isos:
                iso_name = basename(iso)
                iso_size = "{} MB".format(int(self.get_iso_size(iso) / 1024))
                iso_logo = self.logos["iso"]
                for key, logo in list(self.logos.items()):
                    if key != "iso":
                        if key in iso_name.lower():
                            iso_logo = logo
                            break
                self.log.write("ISO on {}: {}, {}, {}".format(mount, iso_name, iso_size, iso_logo))
                isos_list.append([False, iso_logo, iso_name, iso_size])

        # Fill treeview
        self.tvUsbIsosHandler.fillTreeview(contentList=isos_list, columnTypesList=column_types)

    def exec_command(self, command):
        try:
            # Run the command in a separate thread
            self.set_buttons_state(False)
            name = 'cmd'
            t = ExecuteThreadedCommands([command], self.queue)
            self.threads[name] = t
            t.daemon = True
            t.start()
            self.queue.join()
            GLib.timeout_add(1000, self.check_thread, name)

        except Exception as detail:
            ErrorDialog(self.btnExecute.get_label(), detail)

    def check_thread(self, name):
        if self.threads[name].is_alive():
            self.set_progress()
            if not self.queue.empty():
                ret = self.queue.get()
                self.log.write("Queue returns: {}".format(ret), 'check_thread')
                self.queue.task_done()
                self.show_message(ret)
            return True

        # Thread is done
        self.log.write(">> Thread is done", 'check_thread')
        if not self.queue.empty():
            ret = self.queue.get()
            self.queue.task_done()
            self.show_message(ret)
        del self.threads[name]
        self.set_buttons_state(True)
        self.on_cmbDevice_changed()
        self.fill_treeview_usbcreator(self.device["mount"])
        self.set_statusbar_message("{}: {}".format(self.version_text, self.pck_version))
        return False

    def set_buttons_state(self, enable):
        if not enable:
            # Disable buttons
            self.btnExecute.set_sensitive(False)
            self.btnDelete.set_sensitive(False)
            self.btnBrowseIso.set_sensitive(False)
            self.btnRefresh.set_sensitive(False)
            self.btnUnmount.set_sensitive(False)
            self.btnClear.set_sensitive(False)
            self.chkFormatDevice.set_sensitive(False)
            self.chkRepairDevice.set_sensitive(False)
            self.cmbDevice.set_sensitive(False)
            self.txtIso.set_sensitive(False)
        else:
            # Enable buttons and reset progress bar
            self.btnExecute.set_sensitive(True)
            self.btnDelete.set_sensitive(True)
            self.btnBrowseIso.set_sensitive(True)
            self.btnRefresh.set_sensitive(True)
            self.btnUnmount.set_sensitive(True)
            self.btnClear.set_sensitive(True)
            self.chkFormatDevice.set_sensitive(True)
            self.chkRepairDevice.set_sensitive(True)
            self.cmbDevice.set_sensitive(True)
            self.txtIso.set_sensitive(True)
            self.pbUsbCreator.set_fraction(0)

    def get_logos(self):
        logos_dict = {}
        logos_path = join(self.mediaDir, 'logos')
        logos = glob(join(logos_path, '*.png'))
        for logo in logos:
            key = splitext(basename(logo))[0]
            logos_dict[key] = logo
        return logos_dict

    def set_progress(self):
        if exists(self.log_file):
            msg = ''
            last_line = getoutput("tail -50 {} | grep -v DEBUG | grep -v ==".format(self.log_file))
            for line in reversed(last_line):
                # Check for session start line: that is the last line to check
                if ">>>>>" in line and "<<<<<" in line:
                    break
                for chk_line in self.log_lines:
                    if chk_line[0] in line.lower():
                        print((">>> line found: {}".format(line)))
                        word = ''
                        if chk_line[1] == 0:
                            self.pbUsbCreator.pulse()
                            words = line.split(' ')
                            for word in reversed(words):
                                if word.strip() != '':
                                    break
                        else:
                            self.pbUsbCreator.set_fraction(float(chk_line[1] / 100))
                        msg = "{} {}".format(chk_line[2], word)
                        break
                if msg != '':
                    break
            self.set_statusbar_message(msg)

    def set_statusbar_message(self, message):
        if message is not None:
            context = self.statusbar.get_context_id('message')
            self.statusbar.push(context, message)

    def get_devices(self):
        devices = []
        my_devices = getoutput("udisks --enumerate-device-files | egrep '/dev/sd[a-z]$'")
        for device in my_devices:
            info = getoutput("env LANG=C udisks --show-info {}".format(device))
            detachable = False
            has_partition = False
            for line in info:
                if "detachable" in line and "1" in line:
                    detachable = True
                elif "partition" in line:
                    has_partition = True
                if detachable and has_partition:
                    devices.append(device)
                    break
        devices.sort()
        return devices

    def device_has_partition(self, device):
        part_count = getoutput("udisks --show-info {} | grep count | grep -v block".format(device))
        if part_count:
            if "1" in part_count[0]:
                return True
        return False

    def get_device_mount(self, device):
        shell_exec("udisks --mount {}1".format(device))
        mount = getoutput("grep %s1 /etc/mtab | awk '{print $2}' | sed 's/\\040/ /g'" % device)
        if mount:
            return mount[0]
        return ''

    def get_iso_size(self, iso):
        iso_size = getoutput("du -k \"%s\" | awk '{print $1}'" % iso)
        if iso_size:
            return int(iso_size[0])
        return 0

    def unmount_device(self, device):
        shell_exec("udisks --unmount {}1".format(device))
        shell_exec("udisks --detach {}".format(device))

    # Close the gui
    def on_usbcreator_destroy(self, widget):
        # Unmount devices
        for device in self.devices:
            if self.get_device_mount(device) != "":
                self.unmount_device(device)
        # Close the app
        Gtk.main_quit()

    def show_message(self, cmdOutput):
        try:
            self.log.write("Command output: {}".format(cmdOutput), 'show_message')
            ret = int(cmdOutput)
            if ret > 1 and ret != 255:
                if ret == 1:
                    ErrorDialog(self.btnExecute.get_label(), _("Run this application with root permission."))
                elif ret == 2:
                    ErrorDialog(self.btnExecute.get_label(), _("Wrong arguments were passed to usb-creator."))
                elif ret == 3:
                    ErrorDialog(self.btnExecute.get_label(), _("The device was not found or no device was given."))
                elif ret == 4:
                    ErrorDialog(self.btnExecute.get_label(), _("Given ISO path was not found."))
                elif ret == 5:
                    ErrorDialog(self.btnExecute.get_label(), _("Device is in use by another application."))
                elif ret == 6:
                    ErrorDialog(self.btnExecute.get_label(), _("Unable to mount the device."))
                elif ret == 7:
                    ErrorDialog(self.btnExecute.get_label(), _("Md5sum mismatch."))
                elif ret == 8:
                    ErrorDialog(self.btnExecute.get_label(), _("The device has no fat32 partition."))
                elif ret == 9:
                    ErrorDialog(self.btnExecute.get_label(), _("The device has no bootloader installed."))
                elif ret == 10:
                    ErrorDialog(self.btnExecute.get_label(), _("There is not enough space available on the device."))
                else:
                    msg = _("An unknown error accured.\n"
                    "Please, visit our forum for support: http://forums.solydxk.com")
                    ErrorDialog(self.window.get_title(), msg)
            else:
                msg = _("The USB was successfully written.")
                MessageDialog(self.window.get_title(), msg)
        except:
            ErrorDialog(self.btnExecute.get_label(), cmdOutput)
