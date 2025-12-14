import threading
import networkx
import itertools
import enum
import queue

class TaskGroup:
    class Exception(Exception):
        pass

    class Dependency():
        # TODO: have two interfaces
        # Task(arg = TaskGroup.Dependency(task)) # stores all of task output in single variable
        # Task(arg = TaskGroup.Dependency(task, param)) # stores "param" of output in single variable
        # but what about a return value that isn't a dictionary? Like a single value, or a tuple?
        def __init__(self, task, param = None):
            self.task = task

    class ControlLoop:
        def __init__(self, tasks, graph):
            self.tasks = tasks
            self.graph = graph
            self.eventq = queue.Queue()
            self.lock_result = threading.Lock()
            self.results = {}
        def start(self):
            self.thread = threading.Thread(target=self.loop_concurrent)
            self.thread.name = 'TaskGroup.control_loop'
            self.thread.start()
        def wait(self):
            self.thread.join()
        def task_register_hooks(self, task):
            task.add_hook('on_success', self.eventq.put)
            task.add_hook('on_exception', self.eventq.put)
        def task_unregister_hooks(self, task):
            task.remove_hook('on_success', self.eventq.put)
            task.remove_hook('on_exception', self.eventq.put)
        def task_is_ready(self, task):
            """
            Return True if a task's dependencies have finished and the arguments are
            available in self.results. Otherwise returns False.
            """
            with self.lock_result:
                for arg in task.args:
                    if isinstance(arg, TaskGroup.Dependency):
                        if id(arg.task) not in self.results:
                            return False
                for key in task.kwargs:
                    kwarg = task.kwargs[key]
                    if isinstance(kwarg, TaskGroup.Dependency):
                        if id(kwarg.task) not in self.results:
                            return False
                return True
        def task_get_args(self, task):
            """
            Return a task's arguments with all dependencies resolved. Should call
            "task_is_ready" before "task_get_args" to make sure all dependencies are
            available in self.results.
            """
            with self.lock_result:
                args = []
                kwargs = {}
                for arg in task.args:
                    if isinstance(arg, TaskGroup.Dependency):
                        args.append(self.results[id(arg.task)])
                    else:
                        args.append(arg)
                for key in task.kwargs:
                    kwarg = task.kwargs[key]
                    if isinstance(kwarg, TaskGroup.Dependency):
                        kwargs[key] = self.results[id(kwarg.task)]
                    else:
                        kwargs[key] = kwarg
                return args, kwargs
        def loop_concurrent(self):
            """
            This control loop is concurrent. It starts independent tasks immediately without
            waiting and then starts dependent tasks when their predecessor has finished.
            """
            waiting = next(networkx.topological_generations(self.graph))
            while True:
                # make sure to copy the set, otherwise items are skipped.
                for task in waiting.copy():
                    if self.task_is_ready(task):
                        self.task_register_hooks(task)
                        args, kwargs = self.task_get_args(task)
                        task.start(*args, **kwargs)
                        waiting.remove(task)
                        waiting += self.graph.successors(task)
                if len(waiting) > 0:
                    task_id, result = self.eventq.get() # blocks and defers CPU time
                    with self.lock_result:
                        self.results[task_id] = result
                    self.eventq.task_done()
                else:
                    break
            for task in self.tasks:
                task.wait()
                self.task_unregister_hooks(task)
        def loop_serial(self):
            """
            This control loop is serial. It executes tasks one by one, and must wait for the
            current task to finish before starting the next.
            """
            for task in networkx.topological_sort(self.graph):
                self.task_register_hooks(task)
                args, kwargs = self.task_get_args(task)
                task.start(*args, **kwargs)
                task_id, result = self.eventq.get()
                with self.lock_result:
                    self.results[task_id] = result
            for task in self.tasks:
                task.wait()
                self.task_unregister_hooks(task)

    def __init__(self, *args):
        self.tasks = set(args)
        self.graph = networkx.DiGraph()
        self.eventq = queue.Queue()
        # TODO: manage stdout and stderr for all child tasks.
        pass
    def __str__(self):
        # TODO: print the TaskGraph as a mermaid diagram representation.
        pass
    def __repr__(self):
        # TODO: print the TaskGraph as a set of function calls?
        # I can annotate each edge with a type when I "add_edge"
        # e.g. self.graph.add_edge(1, 2, type = 'data' or 'precedence')
        # so I can reconstruct the required calls
        pass
    def start(self):
        """
        This function starts all nodes in the graph.

        Not all nodes are guaranteed to have finished executing when .start() returns.
        Must call .wait() for that. Because if the last nodes were started (they have no
        successors) this function returns without waiting.
        """
        if len(self.graph.nodes) == 0:
            raise TaskGroup.Exception(
                'Called start() on an empty TaskGroup. '
                'You cannot start an empty TaskGroup.')

        # want to isolate state related to a single TaskGroup.start(). Allows tasks in
        # group to be modified while a TaskGroup is running concurrently.
        self.control_loop = TaskGroup.ControlLoop(
            tasks = self.tasks.copy(),
            graph = self.graph.copy(),
        )
        self.control_loop.start()

        # TODO: store start time of task graph
        # TODO: store end time of task graph
        # TODO: store all task start times and end times
        pass
    def cancel():
        # TODO: will cancel all tasks in the graph (basically, wait for current one to
        # stop and not to start other ones)
        pass
    def wait(self):
        self.control_loop.wait()
    def set_stdout():
        # TODO: will set stdout file for task group
        pass
    def set_stderr():
        # TODO: will set stderr file for task group
        pass
    def poll():
        # TODO: requires .cancel() to be implemented.
        # TODO: returns true if still executing, false otherwise (I think this is the convention? I could ask AI for suggestion for this API)
        pass
    def add_precedence(self, *tasks):
        if len(tasks) < 2:
            raise TaskGroup.Exception(
                'TaskGroup.add_precedence called with fewer than two arguments. '
                'Precedence constraints must be expressed in terms of 2 or more tasks')
        # self.add_tasks(*tasks) # TODO: tasks can be added through add_precedence
        for i in range(len(tasks) - 1):
            self.graph.add_edge(tasks[i], tasks[i + 1])
        if exc := self.verify_constraints():
            for i in range(len(tasks) - 1):
                self.graph.remove_edge(tasks[i], tasks[i + 1])
            raise exc
    def add_tasks(self, *args):
        self.tasks.update(args)
        self.graph.add_nodes_from(args)
        edges = list()
        def check_dependency(arg):
            if isinstance(arg, TaskGroup.Dependency):
                if arg.task not in self.tasks:
                    raise TaskGroup.Exception(
                        'Detected TaskGroup Dependency wrapping unrecognized task. '
                        'TaskGroup Dependencies must be added to the TaskGroup. '
                    )
                edges.append((arg.task, task))
        try:
            for task in args:
                for arg in task.args:
                    check_dependency(arg)
                for key in task.kwargs:
                    check_dependency(task.kwargs[key])
            for edge in edges:
                self.graph.add_edge(*edge)
            if exc := self.verify_constraints():
                raise exc
        except TaskGroup.Exception as e:
            for edge in edges:
                self.graph.remove_edge(*edge)
            self.tasks.difference_update(args)
            self.graph.remove_nodes_from(args)
            for task in args:
                task.remove_hook('on_success', self.eventq.put)
                task.remove_hook('on_exception', self.eventq.put)
            raise e
    def remove_tasks(self, *args):
        self.tasks.difference_update(args)
        self.graph.remove_nodes_from(args)
    def verify_constraints(self) -> None | TaskGroup.Exception:
        if not networkx.is_directed_acyclic_graph(self.graph):
            return TaskGroup.Exception(
                'Cycle detected. '
                'Ordering constraints must not introduce cycles. '
                'A TaskGroup must be a directed acyclic graph.')


class Task:
    """
    A Task is the basic unit of execution.

    Usage:

    Specify the function to run in a task thread by passing the "target" argument as
    either the first argument in the argument list or as a keyword argument.

    ```py
    Task(lambda: print("Hello!"))
    # or 
    Task(target = lambda: print("Hello!"))
    ```

    Give the Task a name using the "name" parameter

    ```py
    task = Task(name = "pass")
    assert str(task) == "Task[pass]"
    ```

    Note:

    Each task instance has a unique id. Each thread started by a task is assigned a
    task-unique id that is stored on the thread object. The task id is also stored on
    the thread object. This is used by utilities in the test suite to track task/thread
    invocations during a unit test.

    ```py
    task = Task()
    task.id # task instance id
    task.start()
    task.thread # thread instance
    task.thread.id # thread instance id
    task.thread.task_id # task instance id
    ```
    """

    class Exception(Exception):
        pass

    class Thread(threading.Thread):
        count = itertools.count(0) # not sure what maximum value is, internet suggests infinite
        lock = threading.Lock()
        def __init__(self, task: Task, on_success, on_exception, *args, **kwargs):
            super().__init__(*args, **kwargs)
            with Task.Thread.lock:
                self.id = next(Task.Thread.count)
            self.name = f"TaskThread-{self.id}"
            self.task_id = task.id
            self.result = None
            self.on_success = on_success
            self.on_exception = on_exception
        def run(self):
            """
            Override threading.Thread.run to store return value in self.result.
            (see: inspect.getsource(threading.Thread))
            """
            try:
                if self._target is not None:
                    self.result = self._target(*self._args, **self._kwargs)
                    print("preforming on success: ", self.task_id, ", ", self.result)
                    self.on_success((self.task_id, self.result))
                    # TODO: publish to task group queue? or have hooks?
            except Exception as e:
                self.on_exception((self.task_id, e))
                raise e
            finally:
                del self._target, self._args, self._kwargs

    def __init__(self, target = None, name = None, args = list(), kwargs = dict()):
        self.id = id(self)
        self.target = target if target else lambda: None
        self.args = args
        self.kwargs = kwargs
        if name:
            self.name = name
        elif self.target.__name__ != '<lambda>':
            self.name = self.target.__name__
        else:
            self.name = f"lambda:{self.id}"
        self.hooks = {'on_success': set(), 'on_exception': set()}
    def __str__(self):
        return f"Task[{self.name}]"
    def __repr__(self):
        return f"Task(name={self.name},target={self.target})"
    def start(self, *args, **kwargs):
        self.thread = Task.Thread(
            task=self,
            target=self.target,
            on_success = lambda *a, **kw: self.trigger_hook('on_success', *a, **kw),
            on_exception = lambda *a, **kw: self.trigger_hook('on_exception', *a, **kw),
            args=args,
            kwargs=kwargs,
        )
        print(f"starting {self} [task_id: {self.id}] [thread_id: {self.thread.id}]")
        self.thread.start()
    def wait(self, timeout = None):
        self.thread.join(timeout)
    def set_args(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
    def add_hook(self, hook, fn):
        if hook not in self.hooks:
            raise Task.Exception(f'Request to add unknown hook "{hook}" ')
        self.hooks[hook].add(fn)
    def remove_hook(self, hook, fn):
        if hook not in self.hooks:
            raise Task.Exception(f'Request to remove unknown hook "{hook}" ')
        self.hooks[hook].discard(fn)
    def trigger_hook(self, hook, *args, **kwargs):
        for fn in self.hooks[hook]:
            fn(*args, **kwargs)


