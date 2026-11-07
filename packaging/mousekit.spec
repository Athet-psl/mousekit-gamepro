# Built by packaging/build-rpm.sh, which defines pkg_version and source_root (this checkout).
%global source_date_epoch_from_changelog 0

Name:           mousekit
Version:        %{pkg_version}
Release:        1
Summary:        Mouse settings for KDE Plasma: GamePro lighting, DPI, buttons, gestures
License:        MIT
URL:            https://github.com/Athet-psl/mousekit-gamepro
BuildArch:      noarch
Requires:       python3, python3-evdev, python3-pyqt6, python3-dbus
Recommends:     polkit, libnotify

%description
Mousekit for GamePro sets the lighting, DPI stages and hardware buttons of
GamePro mice (GM500W) and saves them to the mouse. For any mouse it adds
button remapping and hold-and-swipe gestures on KDE Plasma.

%install
%{source_root}/packaging/stage.sh %{buildroot} %{version}

%preun
if [ "$1" -eq 0 ]; then
    systemctl --global disable mousekit.service >/dev/null 2>&1 || true
    for user in $(loginctl list-users --no-legend 2>/dev/null | awk '{print $2}'); do
        systemctl --user --machine="$user@" stop mousekit.service >/dev/null 2>&1 || true
    done
    find /usr/share/mousekit -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
fi

%postun
if [ "$1" -eq 0 ]; then
    udevadm control --reload >/dev/null 2>&1 || true
fi

# After the old version's files are gone, so an update restarts the service on the new code.
%posttrans
python3 -m compileall -q /usr/share/mousekit/mousekit >/dev/null 2>&1 || true
udevadm control --reload >/dev/null 2>&1 || true
udevadm trigger --subsystem-match=input --subsystem-match=hidraw >/dev/null 2>&1 || true
# Start with every graphical session; restart where it already runs (after an update).
systemctl --global enable mousekit.service >/dev/null 2>&1 || true
for user in $(loginctl list-users --no-legend 2>/dev/null | awk '{print $2}'); do
    systemctl --user --machine="$user@" daemon-reload >/dev/null 2>&1 || true
    systemctl --user --machine="$user@" try-restart mousekit.service >/dev/null 2>&1 || true
done

%files
%license /usr/share/doc/mousekit/copyright
%doc /usr/share/doc/mousekit/README.md
%doc /usr/share/doc/mousekit/GM500W-PROTOCOL.md
/usr/bin/mousekit
/usr/bin/mousekitd
/usr/share/mousekit
/usr/lib/systemd/user/mousekit.service
/usr/lib/udev/rules.d/70-mousekit.rules
/usr/share/applications/mousekit.desktop
