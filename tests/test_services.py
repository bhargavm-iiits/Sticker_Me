from scripts import services


class FakeProcess:
    def __init__(self, pid, command, created=100):
        self.pid, self.command, self.created = pid, command, created
        self.children_list = []
        self.stopped = False

    def exe(self):
        return self.command[0]

    def cmdline(self):
        return self.command

    def create_time(self):
        return self.created

    def children(self, recursive):
        return self.children_list

    def terminate(self):
        self.stopped = True

    def wait(self, timeout):
        pass

    def is_running(self):
        return not self.stopped


def test_stop_includes_verified_interpreter_child_but_not_other_commands(monkeypatch):
    parent = FakeProcess(100, ["venv/python.exe", "-m", "backend.app.worker"])
    child = FakeProcess(101, ["managed/python.exe", "-m", "backend.app.worker"], 101)
    unrelated = FakeProcess(102, ["managed/python.exe", "-m", "other_app"], 101)
    parent.children_list = [child, unrelated]
    processes = {process.pid: process for process in (parent, child, unrelated)}
    monkeypatch.setattr(services.psutil, "Process", lambda pid: processes[pid])
    services.stop_owned(services.process_record(parent))
    assert parent.stopped and child.stopped
    assert not unrelated.stopped


def test_reused_pid_is_not_stopped(monkeypatch):
    process = FakeProcess(100, ["python.exe", "-m", "backend.app.worker"], 200)
    monkeypatch.setattr(services.psutil, "Process", lambda pid: process)
    services.stop_owned({"pid": 100, "created": 100, "executable": "python.exe"})
    assert not process.stopped
