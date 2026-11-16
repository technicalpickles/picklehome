import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / "homelab" / "config" / "needrestart-containerd.conf"
OVERRIDE = ROOT / "homelab" / "scripts" / "needrestart-override"

UBUNTU_NEEDRESTART_36_EXCERPT = """\
$nrconf{override_rc} = {
    qr(^dbus) => 0,
    qr(^docker) => 0,
    qr(^unattended-upgrades\\.service$) => 0,
};
my @files = (@FILES@);
foreach my $fn (@files) {
    eval do { local(@ARGV, $/) = $fn; <> };
    die "Error parsing $fn: $@" if($@);
}
"""


def _overrides(tmp_path, files, *units):
    conf = tmp_path / "needrestart.conf"
    conf.write_text(UBUNTU_NEEDRESTART_36_EXCERPT.replace("@FILES@", ", ".join(f"q({f})" for f in files)))
    r = subprocess.run(["perl", str(OVERRIDE), str(conf), *units],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return dict(line.split() for line in r.stdout.splitlines())


def test_stock_restarts_containerd(tmp_path):
    got = _overrides(tmp_path, [], "containerd.service", "docker.service")
    assert got == {"containerd.service": "default", "docker.service": "0"}


def test_fragment_skips_containerd_and_keeps_docker_skipped(tmp_path):
    got = _overrides(tmp_path, [FRAGMENT], "containerd.service", "docker.service", "ssh.service")
    assert got == {"containerd.service": "0", "docker.service": "0", "ssh.service": "default"}


def test_bad_fragment_fails_loudly(tmp_path):
    bad = tmp_path / "bad.conf"
    bad.write_text("$nrconf{override_rc}{qr(^containerd)} = ;\n")
    conf = tmp_path / "needrestart.conf"
    conf.write_text(UBUNTU_NEEDRESTART_36_EXCERPT.replace("@FILES@", f"q({bad})"))
    r = subprocess.run(["perl", str(OVERRIDE), str(conf), "containerd.service"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "Error parsing" in r.stderr
