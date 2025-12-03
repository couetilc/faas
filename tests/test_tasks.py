import pytest
import threading
import contextlib
import collections
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
        if (
            exc_type == Task.Exception and
            'MUST implement method "target"' in str(exc_value)
        ):
            return None # ignore exception
        return args # do not ignore exception
    threading.excepthook = hook
    yield
    threading.excepthook = threading.__excepthook__

@contextlib.contextmanager
def assert_tasks(*, nthread = None, order = None):
    """
    Tracks threads over the execution window of a "with" block.

    USAGE:

    Pass "nthread" to assert on the number of expected threads:

    ```py
    def test_property():
        task = Task()
        with assert_tasks(nthread = 1):
            task.start()
            task.wait()
    ```

    Pass "order" to assert on the task execution order

    ```py
    def test_property():
        group = TaskGroup()
        task1 = Task()
        task2 = Task()
        group.add_precedence(task1, task2)
        with assert_tasks(order = [task1, task2]):
            group.start()
            group.wait()
    ```

    NOTE:

    If not traced over an execution window, there are race conditions:

    ```py
    def test_races():
        task = Task()
        task.start() # short-running task
        assert_tasks(nthread = 1) # may or may not run before the task finishes
        task.wait()
    ```

    So, you trace over execution window:

    ```py
    def test_doesnt_race():
        task = Task()
        with assert_tasks(nthread = 1):
            task.start() # short-running task
            task.wait()
    ```

    And get a count of the active threads during that time.
    """
    class ThreadTracker:
        def __init__(self):
            self.lock = threading.Lock()
            self.threads = set()
            self.tasks = collections.defaultdict(list)
        def track(self, thread):
            with self.lock:
                if thread.id not in self.threads:
                    self.threads.add(thread.id)
                    self.tasks[thread.task_id].append(thread.id)
        @property
        def nthread(self):
            return len(self.threads)
        def assert_nthread(self, n):
            assert self.nthread == n, (
                f"Started {tracker.nthread} non-main thread(s), expected {nthread})")
        def assert_order(self, before: Task, after: Task):
            assert min(self.tasks[before.id]) < min(self.tasks[after.id]), (
                'task "{1}" came before "{0}", expected "{0}" to come before "{1}"'.format(before.name, after.name))

    tracker = ThreadTracker()

    def trace_function(frame, event, arg):
        tracker.track(threading.current_thread())

    threading.settrace(trace_function)
    yield
    threading.settrace(None)

    if nthread != None:
        tracker.assert_nthread(nthread)

    if order != None:
        if len(order) < 2:
            raise Exception("Invalid order argument to assert_tasks. order must contain two or more tasks.")
        for i in range(len(order) - 1):
            tracker.assert_order(order[i], order[i + 1])

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
    with assert_tasks(nthread = 1):
        task.start()
        task.wait()

def test_task_class_method_start_and_wait_cycle():
    task = Task()
    with assert_tasks(nthread = 1):
        task.start()
        task.wait()
    assert_no_threads_remain()
    with assert_tasks(nthread = 1):
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
    with assert_tasks(nthread = 1):
        group = TaskGroup()
        group.add_tasks(Task())
        group.start()
        group.wait()

def test_task_group_start_two_tasks():
    with assert_tasks(nthread = 2):
        group = TaskGroup()
        group.add_tasks(Task(), Task())
        group.start()
        group.wait()


def test_task_group_precedence():
    group = TaskGroup()
    task1 = Task()
    task2 = Task()
    group.add_tasks(task1, task2)
    group.add_precedence(task2, task1)
    with assert_tasks(nthread = 2, order = [task2, task1]):
        group.start()
        group.wait()


def test_task_group_precedence_improper_arguments():
    group = TaskGroup()
    task1 = Task()
    task2 = Task()
    group.add_tasks(task1, task2)
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_precedence()
    assert 'constraints must be expressed in terms of 2 or more' in str(e)
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_precedence(task1)
    assert 'constraints must be expressed in terms of 2 or more' in str(e)


# TODO: my new API for a Task may just be:
# class Task:
#     def __init__(target, *args, **kwargs):
#         self.target = target if target else lambda: None
#         self.args = args
#         self.kwargs = kwargs
#     def start():
# so I don't have to worry about subclassing or unimplemented target methods
