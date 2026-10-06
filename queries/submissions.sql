SELECT a.student_id,COUNT(*) assigned_due,
 SUM(CASE WHEN EXISTS(SELECT 1 FROM responses r WHERE r.student_id=a.student_id AND r.task_id=a.task_id AND r.submitted_at<=:as_of) THEN 1 ELSE 0 END) submitted_due
FROM task_assignments a JOIN tasks t USING(task_id)
WHERE a.assigned_at<=:as_of AND t.available_at<=:as_of AND t.due_at<=:as_of
AND t.due_at>:start AND a.eligibility_status='eligible' GROUP BY a.student_id;
