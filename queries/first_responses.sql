WITH candidates AS (
 SELECT r.*, q.kp_id,q.difficulty,q.max_score,t.comparison_group,t.due_at,
 ROW_NUMBER() OVER(PARTITION BY r.student_id,r.task_id,r.question_id ORDER BY r.attempt_no,r.submitted_at,r.response_id) AS rn
 FROM responses r JOIN questions q USING(question_id) JOIN tasks t USING(task_id)
 JOIN task_assignments a ON a.task_id=r.task_id AND a.student_id=r.student_id
 WHERE r.submitted_at<=:as_of AND t.available_at<=:as_of AND a.assigned_at<=:as_of
 AND a.eligibility_status='eligible' AND r.score IS NOT NULL
)
SELECT * FROM candidates WHERE rn=1 AND submitted_at>:start AND submitted_at<=:end;
