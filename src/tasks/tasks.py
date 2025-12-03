import threading
import networkx
import itertools


class TaskGroup:
    class Exception(Exception):
        pass

    def __init__(self, *args):
        self.tasks = set(args)
        self.graph = networkx.Graph()
        # TODO: manage stdout and stderr for all child tasks.
        # TODO: create some kind of cancel Event, or perhaps a Queue.
        pass
    def __str__(self):
        # TODO: print the TaskGraph as a mermaid diagram representation.
        pass
    def start(self):
        for task in self.tasks:
            task.start()
        # TODO: start each start task
        # TODO: store start time of task graph
        # TODO: store end time of task graph
        pass
    def cancel():
        # TODO: will cancel all tasks in the graph
        pass
    def wait(self):
        for task in self.tasks:
            task.wait()
        # TODO: will wait for all tasks in the graph to complete
        pass
    def set_stdout():
        # TODO: will set stdout file for task group
        pass
    def set_stderr():
        # TODO: will set stderr file for task group
        pass
    def poll():
        # TODO: returns true if still executing, false otherwise (I think this is the convention? I could ask AI for suggestion for this API)
        pass
    def add_precedence(self, *tasks):
        if len(tasks) < 2:
            raise TaskGroup.Exception('TaskGroup.add_precedence called with fewer than two arguments. Precedence constraints must be expressed in terms of 2 or more tasks')
        # TODO: adds an ordering constraint, arguments proceed from left-to-right in
        # diminishing precedence
        # TODO: raise error if port_ready and ssh_ready have not been added as tasks.
        pass
    def add_tasks(self, *args):
        self.tasks.update(args)



class Task:
    """
    A Task is the basic unit of execution.

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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            with Task.Thread.lock:
                self.id = next(Task.Thread.count)
            self.name = f"{self.__class__.__name__}-{self.id}"

    def __init__(self, name = None):
        self.name = name
        if self.name == None:
            self.name = self.__class__.__name__
        self.id = id(self)
    def target(self):
        raise Task.Exception(
            'subclasses of class "Task" MUST implement method "target"')
    def start(self):
        self.thread = Task.Thread(target=self.target,args=(),kwargs={})
        self.thread.task_id = self.id
        self.thread.start()
    def wait(self, timeout = None):
        self.thread.join(timeout)


