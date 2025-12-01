import pytest
from tasks.tasks import Task

# Goal
# run_once = TaskGroup(name = 'run tests once')
# overlay_image = OverlayImageTask(base_image = '')
#
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
    assert 'foo' == PassTask('foo').name
    assert 'foo' == PassTask(name = 'foo').name

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

class PassTask(Task):
    def target(self):
        pass

def test_task_subclass_method_target():
    pass
