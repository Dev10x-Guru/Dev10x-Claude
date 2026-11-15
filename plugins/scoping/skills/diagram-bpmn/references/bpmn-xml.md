# BPMN 2.0 XML Reference

Write the **semantic model only** — process, lanes, nodes, flows.
`render.sh` adds the diagram interchange (DI: every shape, edge, pool
and lane coordinate). Never write `bpmndi:` elements by hand.

## Skeleton: one pool, two lanes

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Definitions_PrReview"
                  targetNamespace="https://dev10x.guru/bpmn/pr-review">
  <bpmn:collaboration id="Collaboration_PrReview">
    <bpmn:participant id="Participant_Team" name="PR review" processRef="Process_PrReview" />
  </bpmn:collaboration>
  <bpmn:process id="Process_PrReview" isExecutable="false">
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_Author" name="Author">
        <bpmn:flowNodeRef>Start_Ready</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Task_Open</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Task_Ci</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Gateway_CiPassed</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Task_Fix</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="Lane_Reviewer" name="Reviewer">
        <bpmn:flowNodeRef>Task_Review</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Gateway_Approved</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>Task_Merge</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>End_Merged</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="Start_Ready" name="Change ready" />
    <bpmn:userTask id="Task_Open" name="Open PR" />
    <bpmn:serviceTask id="Task_Ci" name="Run CI" />
    <bpmn:exclusiveGateway id="Gateway_CiPassed" name="CI passed?" />
    <bpmn:userTask id="Task_Fix" name="Fix and push" />
    <bpmn:userTask id="Task_Review" name="Review PR" />
    <bpmn:exclusiveGateway id="Gateway_Approved" name="Approved?" />
    <bpmn:userTask id="Task_Merge" name="Merge PR" />
    <bpmn:endEvent id="End_Merged" name="PR merged" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_Ready" targetRef="Task_Open" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_Open" targetRef="Task_Ci" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Task_Ci" targetRef="Gateway_CiPassed" />
    <bpmn:sequenceFlow id="Flow_4" name="no" sourceRef="Gateway_CiPassed" targetRef="Task_Fix" />
    <bpmn:sequenceFlow id="Flow_5" sourceRef="Task_Fix" targetRef="Task_Ci" />
    <bpmn:sequenceFlow id="Flow_6" name="yes" sourceRef="Gateway_CiPassed" targetRef="Task_Review" />
    <bpmn:sequenceFlow id="Flow_7" sourceRef="Task_Review" targetRef="Gateway_Approved" />
    <bpmn:sequenceFlow id="Flow_8" name="changes requested" sourceRef="Gateway_Approved" targetRef="Task_Fix" />
    <bpmn:sequenceFlow id="Flow_9" name="approved" sourceRef="Gateway_Approved" targetRef="Task_Merge" />
    <bpmn:sequenceFlow id="Flow_10" sourceRef="Task_Merge" targetRef="End_Merged" />
  </bpmn:process>
</bpmn:definitions>
```

Drop the `collaboration` and `laneSet` for a process with no roles.

## Rules the layout depends on

1. **Every flow node in exactly one lane** when lanes exist. A node in
   no `flowNodeRef` is rejected by name.
2. **One pool per file.** A second `participant` or any `messageFlow`
   is rejected; model each party's process in its own file.
3. **Flows only as `sequenceFlow`.** Do not write `<bpmn:incoming>` /
   `<bpmn:outgoing>` on nodes — the layout derives them from the flows.
4. **A real `targetNamespace`** (a URL you own), not `example.com`.
5. **Stable ids** — `Task_Review`, not `Activity_0x7f3a`. Reviewers diff
   this file.

## Element types

| Element | Use for |
|---------|---------|
| `startEvent` / `endEvent` | One start; one end per distinct outcome (`PR merged`, `PR abandoned`) |
| `userTask` | A person does it (approve, review, fix) |
| `serviceTask` | A system does it with no person (CI, webhook, API call) |
| `manualTask` | Offline physical work (install tires, sign paper) |
| `sendTask` / `receiveTask` | The step *is* sending or awaiting a message |
| `task` | Only when none of the above applies |
| `exclusiveGateway` | Exactly one branch (a question ending in `?`) |
| `parallelGateway` | All branches run; a second one joins them |
| `intermediateCatchEvent` + `timerEventDefinition` | Wait for time (`3 days pass`) |

Name tasks verb-first (`Review PR`); name gateways as the question and
their outgoing flows as the answers (`yes` / `no`, `approved`).
