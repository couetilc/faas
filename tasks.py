
# TODO: some type of TaskThread class
# - needs to specify dependencies:
#   - parent dependencies: thread does not execute until condition from parent is satisfied.
#   - child dependencies: communicate conditions somehow
# - holds reference to a cancel event used by each TaskThread
# - maybe Queue for communication between parents/childs? (instead of single Event, could have queue that receives event messages, and also shuts down when parent finishes)
#   - queue's can send messages: (like "ready")
#   - queue's can end. See "Queue.shutdown()"
# - timing tracking (start time, end time, duration)
# - automatic resource cleanup after completion.
# - handles interrupts well and across all tasks
# - task's childrens execute concurrently.

# TODO: maybe TaskGraph stores a global context dictionary, that each task receives as
# an argument?

class TaskGraph:
    def __init__():
        # TODO: manage stdout and stderr for all child tasks.
        # TODO: create some kind of cancel Event, or perhaps a Queue.
        pass
    def __str__(self):
        # TODO: print the TaskGraph as a mermaid diagram representation.
        pass
    def start():
        # TODO: start each start task
        # TODO: store start time of task graph
        # TODO: store end time of task graph
        pass
    def cancel():
        # TODO: will cancel all tasks in the graph
        pass
    def wait():
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
    def add_precedence():
        # TODO: adds an ordering constraint, arguments proceed from left-to-right in
        # diminishing precedence
        # TODO: raise error if port_ready and ssh_ready have not been added as tasks.
        pass


# TODO graph stuff edge-cases:
# - make sure no cycles? What would this even look like?
# - make sure tasks cannot depend on itself?
# - any other gotchas from literature or otherwise?
# - make sure runtime arguments are valid for the graph, that is, that the dependencies
# and their data requirements are satisfied. For example, if the port check node is
# dependent on the qemu vm node to publish the vm port.

class Task:
    def __init__(self, name: 'string'):
        self.name = name
        # TODO: create a thread.
    def target():
        raise NotImplementedError(
            'subclasses of class "Task" MUST implement method "target"')
    def start():
        self.thread = threading.Thread(target=self.target,args=(),kwargs={})

class SleepTask(Task):
    def __init__(self, sleep_for):
        self.sleep_for = sleep_for
        super().__init__(f"sleep for {sleep_for}s")

# My test TaskGroups will be simpler:
# First things first:
#   task = Task(name: 'sleep for 1s')
#   task.run()
#   task.wait()
# Then introduce TasksGroup:
#   group = TaskGroup(name: 'sleeps')
#   task = Task(name: 'sleep for 1s')
#   group.add_start_task(task)
#   group.run()
#   group.wait()
# Then introduce dependencies:
#   group = TaskGroup(name: 'sleeps')
#   task1 = Task(name: 'sleep for 1s')
#   task2 = Task(name: 'sleep for 2s')
#   group.add_start_task(task)
#   task2.depends_on(task1)
#   group.run()
#   group.wait()

# The first TaskGroup I will implement is:
# TaskGroup(name: 'run tests once')
# - Task(name: 'create overlay image')
# - Task(name: 'start qemu vm')
# - Task(name: 'wait until port is ready')
# - Task(name: 'wait until ssh is ready')
# - Task(name: 'rsync files once')
# - Task(name: 'run tests once')
# def main():
#   group = TaskGroup(name: 'run tests once')
#   task1 = Task(name: 'create overlay image')
#   task2 = Task(name: 'start qemu vm')
#   task3 = Task(name: 'wait until port is ready')
#   task4 = Task(name: 'wait until ssh is ready')
#   task5 = Task(name: 'rsync files once')
#   task6 = Task(name: 'run tests once')
#   group.add_start_task(task1)
#   task2.depends_on(task1)
#   task3.depends_on(task2)
#   task4.depends_on(task3)
#   task5.depends_on(task4)
#   task6.depends_on(task5)
#   group.set_stdout(sys.stdout)
#   group.set_stderr(sys.stderr)
#   group.run()
#   group.wait()
#   print(group.stdout)
#   print(group.stderr)

#   I need to figure out how the data dependencies between tasks will be expressed, not
# just their sequence. In fact, the sequence can be derived by the data dependencies.
# That's actually a better and more modern way to express this. Then you let the graph
# sort algorithm figure out the sequencing order.
#   So TaskGroup has to evaluate the sequencing order. And enforce the rules around data
# dependencies. So no need for explicit task class I guess? Not quite, the Tasks are
# user-defined, and will be re-used.
#   I still need a wait to manually specify some sequencing rules for tasks that don't have a data dependency but have a sequencing dependency.
# 
# overlay_image = OverlayImageTask(name = 'create overlay image', base_image = 'ubuntu.img')
# vm = QemuTask(
#   name = 'run test vm',
#   image = OverlayImageTask.overlay_image, # data dependency expression
# )
# port_ready = PortReadyTask()
# ssh_ready = SshReadyTask()
# ssh_ready.after(port_ready)
# # OR
# port_ready.before(ssh_ready)
# run_once = TaskGroup(name: 'run tests once')
# run_once.add_task(vm) # order doesn't matter
# run_once.add_task(overlay_image)
# print(run_once) # prints mermaid diagram of the execution order
# run_once.start()
# run_once.wait()

# Ok, so order will be determined by precedence statements.
# port_ready = PortReadyTask()
# ssh_ready = SshReadyTask()
# run_once = TaskGroup(name: 'run tests once')
# run_once.add_task(port_ready)
# run_once.add_task(ssh_ready)
# run_once.add_precedence(port_ready, ssh_ready) 
#
# Perhaps each data dependency will simply be an annotated kwarg to a Task's __init__
# function.
# class SleepTask:
#     def __init__(self, sleep_for):
#         super().__init__(f"sleep for {sleep_for}")
# We can inspect function signatures:
# import inspect
# sig = inspect.signature(Task.__init__)
# for p in sig.parameters:
#     # https://docs.python.org/3/library/inspect.html#inspect.Parameter
#     print(f"Parameter: {p.name}, Kind: {p.kind}, Annotation: {p.annotation}")
# class OverlayImageTask(Task):
#     image: str # publishes "image" as part of TaskGroup context
# class QemuTask(Task):
#     # TaskGroup will read Task.__annotations__ and inject arguments by name
#     def __init__(image):
#         self.image = image

# Ok, so data dependencies will be identified using class variables and annotations. Any
# class variable on the Task subclass will be placed into the TaskGroup context. (that
# context should be read-only? for now, yes)

# class OverlayImageTask(Task):
#     image: str
# class QemuVmTask(Task):
#     ssh_port: int
# class PortReadyTask(Task):
#     def __init__(self, ssh_port: DataDependency(QemuVmTask.ssh_port)):
#         pass
# 
# Yeah this is weird because I need a binding between an argument to a Task subclass, 
# 
# Hmmm maybe you could be explicit about a data dependency if the name is wrong:
#   TwoTask(port = DataDependency(QemuVmTask, 'ssh_port'))
# 
# This could perhaps be a python "protocol" instead https://typing.python.org/en/latest/spec/protocol.html
