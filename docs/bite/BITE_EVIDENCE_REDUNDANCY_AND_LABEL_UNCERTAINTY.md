# BITE evidence redundancy and label uncertainty

For binary candidate correctness, a prior `p(s)` supports equal-cost stopping
risk `min(p,1-p)`. Estimating the value of an action additionally requires its
conditional observation kernel and the posterior induced by each outcome. This
phase estimates neither `K_a` nor expected risk reduction.

If an action observation satisfies `O_a=f(s)` almost surely, then conditioned on
`s` it has zero mutual information with `H`. The observed 73/73 identical exact
repeats are consistent with deterministic repetition in that deployment. They
do not prove the almost-sure premise for every image, execution or checkpoint,
so they are an action-space warning rather than a universal theorem.

Label uncertainty is different from candidate uncertainty. At least five
quantities must remain separate:

1. uncertainty about whether the candidate is visually correct;
2. incompleteness or error in `H_annotation`;
3. estimation uncertainty in the initial prior;
4. uncertainty in a future action-observation kernel;
5. unsupported source/checkpoint shift.

The exact sensitivity bounds show how much hypothetical endpoint correction can
change the observed prior comparison while holding predictions fixed. They do
not discover omissions, recalibrate visual truth, identify a causal kernel, or
guarantee a downstream decision. A future BITE risk claim must propagate these
sources under explicit assumptions, validate the action kernel on independent
groups, and charge operational cost. No planner, Bellman optimization, posterior
update or identifiability certificate is implemented here.

