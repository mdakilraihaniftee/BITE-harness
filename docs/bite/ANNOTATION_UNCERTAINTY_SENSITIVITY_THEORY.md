# Annotation-uncertainty sensitivity theory

This analysis measures robustness of the **frozen observed paired evaluation**
to hypothetical endpoint corrections. It neither estimates an annotation-error
rate nor covers refitting models after corrected labels.

For fixed score-model probability `p_B`, baseline probability `p_A`, and binary
label `y`, the paired Brier contribution is

\[
d_i(y)=p_{B,i}^2-p_{A,i}^2-2y(p_{B,i}-p_{A,i}).
\]

Consequently, flipping the label changes the contribution by

\[
e_i=d_i(1-y)-d_i(y)=-2(1-2y)(p_{B,i}-p_{A,i}).
\]

For at most `m` flips, every feasible total is the observed total plus a sum of
at most `m` eligible effects. Therefore the exact minimum selects up to `m`
strictly negative effects in ascending order; the exact maximum selects up to
`m` strictly positive effects in descending order. An exchange argument proves
optimality: replacing any selected effect with a more favorable unselected
effect cannot worsen the relevant objective, and zero/adverse effects are never
needed under an at-most constraint. Synthetic exhaustive enumeration confirms
the implementation for every budget in the test world.

Three uncertainty sets are kept distinct:

1. suspected missing annotations: only original negatives with no annotated
   queried-class instance may change 0→1;
2. all annotation negatives: any 0 may change to 1;
3. two-sided: any declared label may flip.

None says the eligible labels are actually wrong.

## Primary expansion: score-only minus constant Brier

### Suspected-missing-annotation scenario

| Endpoint | Eligible | Budget | Minimum | Maximum | Includes zero |
| --- | ---: | ---: | ---: | ---: | --- |
| .50 | 159 | 0 | -0.044698 | -0.044698 | no |
| .50 | 159 | 1 | -0.048591 | -0.043070 | no |
| .50 | 159 | 2 | -0.052359 | -0.041442 | no |
| .50 | 159 | 5 | -0.062392 | -0.036561 | no |
| .50 | 159 | 10 | -0.072856 | -0.028438 | no |
| .50 | 159 | 20 | -0.084118 | -0.012252 | no |
| .50 | 159 | 40 | -0.087521 | 0.019288 | yes |
| .75 | 159 | 0 | -0.030534 | -0.030534 | no |
| .75 | 159 | 1 | -0.034552 | -0.028827 | no |
| .75 | 159 | 2 | -0.038208 | -0.027120 | no |
| .75 | 159 | 5 | -0.046024 | -0.022003 | no |
| .75 | 159 | 10 | -0.053752 | -0.013487 | no |
| .75 | 159 | 20 | -0.061278 | 0.003504 | yes |
| .75 | 159 | 40 | -0.062199 | 0.036333 | yes |

The smallest candidate budgets capable of reversing the observed primary
ranking are 28 suspected-missing flips at .50 and 18 at .75. The same minima
hold when every negative is eligible. Under the broader two-sided mechanism,
the minima are 12 and 9. The reversal-dominating suspected omissions are mostly
low-score queried classes—especially jellyfish, penguin and starfish—for which
the score model predicted much less than the fold constant. This describes the
algebraic worst case, not visual truth.

## Pilot sensitivity

The pilot has only 32 suspected-missing eligible negatives. Its score advantage
can reverse with 2 such flips at .50 and 3 at .75; a two-sided reversal needs
only one flip at either threshold. At the prespecified budgets, the suspected-
missing intervals first include zero at `m=2` (.50) and `m=5` (.75). This
fragility is consistent with its sparse positive support.

Weighted group-balanced versions use weight `1/n_g` for each row in group `g`
and the same exact effect ordering. Complete case-level and group-balanced
tables, selected identities, effective clipped budgets, and percentages are in
`outputs/bite/phase04c1b/label_sensitivity/`.

These bounds condition on old coefficients and old predictions. Correcting
labels and retraining could change preprocessing, coefficients, and all
probabilities; that uncertainty is outside this result. `H_annotation` also
remains distinct from visually verified correctness and from threshold-specific
human geometry.

