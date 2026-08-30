import { Link } from "react-router-dom";

import { useInterfaceLocale } from "../interfaceLocale";

/**
 * 购买额度, beside the refusal that needs it.
 *
 * `docs/design/credits-in-the-workbench.md`: 额度不足 is never a bare failure
 * and never a figure. A refusal a user cannot act on has told them off rather
 * than told them something — and buying is the only remedy, since this is the
 * one refusal in the workbench that waiting does not fix.
 */
export function BuyCreditsLink(): React.ReactElement {
  const { t } = useInterfaceLocale();
  return (
    <Link className="button button--quiet credit-refusal__buy" to="/account">
      {t("购买额度")}
    </Link>
  );
}
