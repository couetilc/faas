import pytest
import time
import networkx
import threading
import contextlib
import collections
import queue
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
    yield from assert_no_threads_remain()

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
            if thread.name == 'TaskGroup.control_loop':
                return
            with self.lock:
                if thread.id not in self.threads:
                    self.threads.add(thread.id)
                    self.tasks[thread.task_id].append(thread.id)
        @property
        def nthread(self):
            return len(self.threads)
        def assert_nthread(self, n):
            assert self.nthread == n, (
                f"Started {tracker.nthread} non-main thread(s), expected {nthread}")
        def assert_order(self, before: Task, after: Task):
            assert min(self.tasks[before.id]) < min(self.tasks[after.id]), (
                'task "{1}" came before "{0}", expected "{0}" to come before "{1}"'.format(before, after))

    tracker = ThreadTracker()

    def trace_function(frame, event, arg):
        tracker.track(threading.current_thread())

    threading.settrace(trace_function)
    yield tracker
    threading.settrace(None)

    if nthread != None:
        tracker.assert_nthread(nthread)

    if order != None:
        if len(order) < 2:
            raise Exception("Invalid order argument to assert_tasks. order must contain two or more tasks.")
        for i in range(len(order) - 1):
            tracker.assert_order(order[i], order[i + 1])

@contextlib.contextmanager
def catch_thread_exceptions():
    exceptions = queue.Queue()
    def hook(args):
        exc_type, exc_value, exc_traceback, thread = args
        if exc_type != Task.Exception:
            exceptions.put(exc_type(exc_value).with_traceback(exc_traceback))
            return args
    threading.excepthook = hook
    yield exceptions
    threading.excepthook = threading.__excepthook__

@pytest.fixture(autouse=True)
def raise_thread_exceptions_in_main_thread(request):
    """
    This fixture takes exceptions raised in a thread and raises them in a main thread.
    This is done to signal a test failure to pytest. No threads in our test suite should
    raise uncaught exceptions.
    """
    if request.node.get_closest_marker("disable_main_thread_exceptions"):
        yield
        return
    with catch_thread_exceptions() as exceptions:
        yield
    while not exceptions.empty():
        raise exceptions.get()

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

def test_task_subclass_method_target():
    event = threading.Event()
    task = Task(lambda: event.set())
    assert not event.is_set()
    task.start()
    task.wait()
    assert event.is_set()

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
    task1 = Task(name = '1')
    task2 = Task(name = '2')
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

def test_task_initialize_target_arg():
    event = threading.Event()
    task = Task(lambda: event.set())
    assert not event.is_set()
    with assert_tasks(nthread = 1):
        task.start()
        task.wait()
    assert event.is_set()

def test_task_initialize_target_kwarg():
    event = threading.Event()
    task = Task(target=lambda: event.set())
    assert not event.is_set()
    with assert_tasks(nthread = 1):
        task.start()
        task.wait()
    assert event.is_set()

def test_task_class_name():
    explicit_name = Task(name = 'foo')
    assert 'Task[foo]' == str(explicit_name)
    def bar():
        pass
    implicit_name = Task(target = bar)
    assert 'Task[bar]' == str(implicit_name)
    default_name = Task()
    assert 'Task[lambda:' in str(default_name) and ']' == str(default_name)[-1]

# TODO: how to make sure added nodes are a directed acyclic graph?
def test_task_group_precedence_with_self_loop():
    """
    A self-loop can produce a never-ending task group, they are not allowed.
    """
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2')
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_precedence(task1, task1)
    assert 'Cycle detected' in str(e)

def test_task_group_precedence_with_cycles():
    """
    A cycle can produce a never-ending task group, they are not allowed.
    """
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2')
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_precedence(task1, task2, task1)
    assert 'Cycle detected' in str(e)

def test_task_group_precedence_with_cycles_recovery():
    """
    If an add_precedence call produces a cycle, the TaskGroup graph should not be
    updated, the edges should be discarded, and the graph should still conform to all
    constraints.
    """
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2')
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_precedence(task1, task1)
    assert not isinstance(group.verify_constraints(), TaskGroup.Exception)

def test_task_group_stores_tasks():
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2')
    task3 = Task(name = '3')
    group.add_tasks(task1)
    assert task1 in group.tasks
    group.add_tasks(task2, task3)
    assert task2 in group.tasks
    assert task3 in group.tasks

def test_task_group_removes_tasks():
    group = TaskGroup()
    task1 = Task(name = '1')
    group.add_tasks(task1)
    assert task1 in group.tasks
    group.remove_tasks(task1)
    assert task1 not in group.tasks
    task2 = Task(name = '2')
    group.add_tasks(task1, task2)
    assert task1 in group.tasks
    assert task2 in group.tasks
    group.remove_tasks(task1, task2)
    assert task1 not in group.tasks
    assert task2 not in group.tasks

# TODO: I think data dependencies are the next thing to tackle.
def test_task_group_data_dependencies_are_ordered_args():
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2',
                 args = [TaskGroup.Dependency(task1)],
                 target = lambda x: None)
    group.add_tasks(task2, task1)
    with assert_tasks(nthread = 2, order = [task1, task2]):
        group.start()
        group.wait()

def test_task_group_data_dependencies_are_ordered_kwargs():
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2',
                 kwargs = {'data': TaskGroup.Dependency(task1)},
                 target = lambda data: None)
    group.add_tasks(task2, task1)
    with assert_tasks(nthread = 2, order = [task1, task2]):
        group.start()
        group.wait()

def test_task_group_data_dependency_is_not_in_task_group():
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2', kwargs = {'data': TaskGroup.Dependency(task1)})
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_tasks(task2)
        assert 'TaskGroup Dependency wrapping unrecognized task' in str(e)
    assert task1 not in group.tasks
    assert task2 not in group.tasks
    assert not group.graph.has_edge(task1, task2)
    assert task1 not in group.graph
    assert task2 not in group.graph

def test_task_group_data_dependency_with_self_loop():
    group = TaskGroup()
    task1 = Task(name = '1')
    task1.set_args(TaskGroup.Dependency(task1))
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_tasks(task1)
        assert 'Cycle detected' in str(e)
    assert task1 not in group.tasks
    assert not group.graph.has_edge(task1, task1)
    assert task1 not in group.graph

def test_task_group_data_dependency_with_cycle():
    group = TaskGroup()
    task1 = Task(name = '1')
    task2 = Task(name = '2')
    task1.set_args(TaskGroup.Dependency(task2))
    task2.set_args(TaskGroup.Dependency(task1))
    with pytest.raises(TaskGroup.Exception) as e:
        group.add_tasks(task1, task2)
        assert 'TaskGroup Dependency wrapping unrecognized task' in str(e)
    assert task1 not in group.tasks
    assert task2 not in group.tasks
    assert not group.graph.has_edge(task1, task2)
    assert task1 not in group.graph
    assert task2 not in group.graph

def test_task_hook_on_success():
    task1 = Task(name = '1', target = lambda: 'foo')
    def assert_foo(event):
        task_id, result = event
        assert task_id == id(task1)
        assert result == 'foo'
    task1.add_hook('on_success', assert_foo)
    with assert_tasks(nthread = 1):
        task1.start()
        task1.wait()

def test_task_hook_on_success_multiple():
    task1 = Task(name = '1', target = lambda: 'foo')
    def assert_foo(event):
        task_id, result = event
        assert task_id == id(task1)
        assert result == 'foo'
    def assert_not_bar(event):
        task_id, result = event
        assert task_id == id(task1)
        assert result != 'bar'
    task1.add_hook('on_success', assert_foo)
    task1.add_hook('on_success', assert_not_bar)
    with assert_tasks(nthread = 1):
        task1.start()
        task1.wait()

def test_task_hook_removal():
    task1 = Task(name = '1', target = lambda: 'foo')
    def assert_not_foo(event):
        task_id, result = event
        task_id = id(task1)
        assert result != 'foo'
    task1.add_hook('on_success', assert_not_foo)
    task1.remove_hook('on_success', assert_not_foo)
    with assert_tasks(nthread = 1):
        task1.start()
        task1.wait()

def test_task_hook_unknown():
    task1 = Task(name = '1')
    with pytest.raises(Task.Exception) as e:
        task1.add_hook('bar', lambda: None)
    assert 'add unknown hook "bar"' in str(e)
    with pytest.raises(Task.Exception) as e:
        task1.remove_hook('bar', lambda: None)
    assert 'remove unknown hook "bar"' in str(e)

def test_task_group_data_dependencies_share_data_args():
    group = TaskGroup()
    task1 = Task(name = '1', target=lambda: 'foo')
    def assert_foo(data):
        assert data == 'foo'
    task2 = Task(
        name = '2',
        target=assert_foo,
    )
    task2.set_args(TaskGroup.Dependency(task1))
    group.add_tasks(task2, task1)
    with assert_tasks(nthread = 2, order = [task1, task2]):
        group.start()
        group.wait()

def test_task_group_data_dependencies_share_data_kwargs():
    group = TaskGroup()
    task1 = Task(name = '1', target=lambda: 'foo')
    def assert_foo(data):
        assert data == 'foo'
    task2 = Task(
        name = '2',
        target=assert_foo,
    )
    task2.set_args(data = TaskGroup.Dependency(task1))
    group.add_tasks(task2, task1)
    with assert_tasks(nthread = 2, order = [task1, task2]):
        group.start()
        group.wait()

def test_task_group_started_with_no_tasks():
    group = TaskGroup()
    with pytest.raises(TaskGroup.Exception) as e:
        group.start()
    assert 'empty TaskGroup' in str(e)

def test_task_group_start_concurrently():
    """
    To test threads are started concurrently, we start two sleeping threads and check
    the started thread count before the sleeps elapse. If the tasks are executed
    concurrently, thread count should be greater than one. If the tasks are executed
    serially, thread count should only be one, the second task isn't started until the
    first task has finished, which will be after our test thread checks the thread
    count.
    """
    group = TaskGroup()
    task1 = Task(name = '1', target = lambda: time.sleep(.2))
    task2 = Task(name = '2', target = lambda: time.sleep(.2))
    group.add_tasks(task1, task2)
    with assert_tasks(nthread = 2) as tracker:
        group.start()
        # give time for threads to start
        time.sleep(.1)
        # at this point threads are started but sleeping.
        assert tracker.nthread == 2
        # assertion is not true when serial, not enough time elapsed for a task to
        # finish, implying the next one was not started.
        group.wait()

def test_task_group_dependency_param_dict():
    group = TaskGroup()
    def foobar():
        return {'foo': 'bar'}
    def assert_bar(bar):
        assert bar == 'bar'
    task1 = Task(name = '1', target = foobar)
    task2 = Task(name = '2', target = assert_bar)
    task2.set_args(bar = TaskGroup.Dependency(task1, 'foo'))
    group.add_tasks(task1, task2)
    with assert_tasks(nthread = 2, order = [task1, task2]):
        group.start()
        group.wait()

@pytest.mark.disable_main_thread_exceptions
def test_task_group_dependency_param_no_match():
    """
    Have to disable the main thread exception fixture to test whether a particular
    exception was raised by the control loop, otherwise the exception will be raised
    after this test completes and outside of where the test code can handle it.

    TODO: It might be better to not raise exceptions in the control loop, and instead
    have it stop and collect error messages, which are then raised on .wait() or can be
    checked with .errors(). Then I wouldn't need this pytest marker hack.
    """
    def quxbar():
        return {'qux': 'bar'}
    def assert_bar(bar):
        assert bar == 'bar'
    group = TaskGroup()
    task1 = Task(name = '1', target = quxbar)
    task2 = Task(name = '2', target = assert_bar)
    task2.set_args(bar = TaskGroup.Dependency(task1, 'foo'))
    group.add_tasks(task1, task2)
    with catch_thread_exceptions() as exceptions:
        with assert_tasks(nthread = 1):
            group.start()
            group.wait()
    with pytest.raises(TaskGroup.Exception) as e:
        while not exceptions.empty():
            raise exceptions.get()

def test_task_group_collects_error():
    group = TaskGroup()
    exc = Exception()
    def raise_error():
        raise exc
    task = Task(name = '1', target = raise_error)
    group.add_tasks(task)
    group.start()
    group.wait()
    assert len(group.errors()) > 0
    assert exc in group.errors()

def test_task_group_collects_errors():
    group = TaskGroup()
    def raise_error():
        raise Exception()
    task1 = Task(name = '1', target = raise_error)
    task2 = Task(name = '2', target = raise_error)
    group.add_tasks(task1, task2)
    group.start()
    group.wait()
    assert len(group.errors()) == 2

def test_task_group_cancels_tasks():
    group = TaskGroup()
    task1 = Task(name = '1', target = lambda: time.sleep(.1))
    task2 = Task(name = '2', target = lambda: time.sleep(.1))
    group.add_tasks(task1)
    group.add_precedence(task1, task2)
    with assert_tasks(nthread = 1):
        group.start()
        group.cancel()
        group.wait()


# TODO: there is not too much left. I want to:
# - implement .cancel and .errors like in above test
# - track start times and end times for tasks and task groups
# - print debugging output to stdout, stderr, that is, capture any thread output. I
# think? Basically, what do I want my verbose output to be?


# qemu_vm = QemuVmTask(image = TaskGroup.Dependency(overlay_image, 'image'))
# port_ready = PortReadyTask(port = TaskGroup.Dependency(vm, 'ssh_port'))
# ssh_ready = PortReadyTask(port = TaskGroup.Dependency(vm, 'ssh_port'))
# # calculate the correctness of the task dependency graph on every add,
# # but allow adding multiple tasks at once and have dependency graph correctness
# # evaluated with all tasks considered.
# run_once.add_tasks(image_task, qemu_vm, port_ready, ssh_ready)
# run_once.add_precedence(port_ready, ssh_ready)
