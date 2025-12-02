import pytest
import threading
import contextlib
from tasks.tasks import Task, TaskGroup

def assert_no_threads_remain():
    yield
    threads = [
        thread for thread in threading.enumerate()
        if thread != threading.main_thread()]
    assert len(threads) == 0, f"Found {len(threads)} non-main thread{
        's' if len(threads) != 1 else ''}, expected 0"

@pytest.fixture(autouse=True)
def fixture_assert_no_threads_remain():
    assert_no_threads_remain()

@pytest.fixture(autouse=True)
def ignore_task_exception_from_default_target_method(request):
    """
    The base Task class raises an error if not overriden. Some tests use the base class
    for simplicity. Let's ignore that specific error for all tests. Otherwise, if a test
    fails while using the base Task class, the Task.Exception will display and distract.
    """
    def hook(args):
        exc_type, exc_value, exc_traceback, thread = args
        if exc_type == Task.Exception and 'MUST implement method "target"' in exc_value:
            return None # ignore exception
        return args # do not ignore exception
    threading.excepthook = hook
    yield
    threading.excepthook = threading.__excepthook__

@contextlib.contextmanager
def assert_n_threads(n):
    """
    Counts and asserts the number of threads started over the context. If not traced,
    there is a race condition:

    ```py
    def test_races():
        task = Task()
        task.start() # short-running task
        assert_n_threads(1) # may or may not run before the task finishes
        task.wait()
    ```

    So, you trace over execution window:

    ```py
    def test_doesnt_race():
        task = Task()
        with assert_n_threads(1):
            task.start() # short-running task
            task.wait()
    ```

    And get a count of the active threads during that time.
    """
    threads = {}
    def mark_thread(frame, event, arg):
        if threading.current_thread() not in threads:
            threads[threading.current_thread()] = True
    threading.settrace(mark_thread)
    yield
    threading.settrace(None)
    assert len(threads) == n, f"Started {len(threads)} non-main thread{
        's' if len(threads) != 1 else ''}, expected {n}"


# Goal
# run_once = TaskGroup(name = 'run tests once')
# overlay_image = OverlayImageTask(base_image = '')

# qemu_vm = QemuVmTask(image = TaskGroup.Dependency(overlay_image, 'image'))
# port_ready = PortReadyTask(port = TaskGroup.Dependency(vm, 'ssh_port'))
# ssh_ready = PortReadyTask(port = TaskGroup.Dependency(vm, 'ssh_port'))
# # calculate the correctness of the task dependency graph on every add,
# # but allow adding multiple tasks at once and have dependency graph correctness
# # evaluated with all tasks considered.
# run_once.add_tasks(image_task, qemu_vm, port_ready, ssh_ready)
# run_once.add_precedence(port_ready, ssh_ready)

def test_task_class_has_name():
    assert 'foo' == Task('foo').name
    assert 'foo' == Task(name = 'foo').name

def test_task_subclass_has_name():
    class FooTask(Task):
        pass
    assert 'foo' == FooTask('foo').name
    assert 'foo' == FooTask(name = 'foo').name

def test_task_class_has_name_default():
    assert 'Task' == Task().name
    assert 'Task' == Task().name

def test_task_subclass_has_name_default():
    class FooTask(Task):
        pass
    assert 'FooTask' == FooTask().name
    assert 'FooTask' == FooTask().name

def test_task_class_method_target_raises_error():
    with pytest.raises(Task.Exception) as e:
        Task().target()
    assert 'MUST implement method "target"' in str(e)

def test_task_class_method_start_and_wait():
    task = Task()
    with assert_n_threads(1):
        task.start()
        task.wait()

def test_task_class_method_start_and_wait_cycle():
    task = Task()
    with assert_n_threads(1):
        task.start()
        task.wait()
    assert_no_threads_remain()
    with assert_n_threads(1):
        task.start()
        task.wait()

class MockTask(Task):
    def __init__(self, event = threading.Event()):
        self.event = event
    def target(self):
        self.event.set()

def test_task_subclass_method_target():
    task = MockTask()
    assert not task.event.is_set()
    task.start()
    task.wait()
    assert task.event.is_set()

def test_task_group():
    group = TaskGroup()

def test_task_group_start_one_task():
    with assert_n_threads(1):
        group = TaskGroup()
        group.add_tasks(Task())
        group.start()
        group.wait()

def test_task_group_start_two_tasks():
    with assert_n_threads(2):
        group = TaskGroup()
        group.add_tasks(Task(), Task())
        group.start()
        group.wait()
