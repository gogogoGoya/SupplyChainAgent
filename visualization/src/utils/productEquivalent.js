const DEFAULT_PRODUCT_ID = 'beer';
const DEFAULT_RECIPE_MAP = {
  Malt: 100,
  Hops: 10,
  Yeast: 5,
};

const toFiniteNumber = (value, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

export const extractRecipeConfigFromRunMeta = (runMeta) => {
  const recipeActions = runMeta?.scenario_config?.initial_action_batches?.init_action_3 || [];
  const recipeAction = recipeActions.find(
    (item) => item?.action?.action_name === 'set_product_recipe'
  );
  const actionParam = recipeAction?.action?.action_param || {};
  const rawMaterials = actionParam.raw_materials || DEFAULT_RECIPE_MAP;
  const recipeMap = Object.entries(rawMaterials).reduce((acc, [materialId, amount]) => {
    const numericAmount = toFiniteNumber(amount, 0);
    if (numericAmount > 0) {
      acc[materialId] = numericAmount;
    }
    return acc;
  }, {});

  return {
    productId: actionParam.product_id || DEFAULT_PRODUCT_ID,
    recipeMap: Object.keys(recipeMap).length > 0 ? recipeMap : { ...DEFAULT_RECIPE_MAP },
  };
};

export const buildQuantityView = (enabled, runMeta) => {
  const { productId, recipeMap } = extractRecipeConfigFromRunMeta(runMeta);
  return {
    enabled: Boolean(enabled),
    productId,
    recipeMap,
  };
};

export const isConvertibleRawMaterial = (itemId, quantityView) => {
  if (!quantityView?.enabled) {
    return false;
  }
  return toFiniteNumber(quantityView?.recipeMap?.[itemId], 0) > 0;
};

export const convertQuantityByItem = (quantity, itemId, quantityView) => {
  const numericQuantity = toFiniteNumber(quantity, 0);
  const recipeAmount = toFiniteNumber(quantityView?.recipeMap?.[itemId], 0);
  if (quantityView?.enabled && recipeAmount > 0) {
    return numericQuantity / recipeAmount;
  }
  return numericQuantity;
};

export const sumConvertedFieldByItemMap = (itemsById, fieldName, quantityView) =>
  Object.entries(itemsById || {}).reduce(
    (sum, [itemId, item]) => sum + convertQuantityByItem(item?.[fieldName], itemId, quantityView),
    0
  );

export const sumConvertedFieldByList = (items, quantityField, itemField, quantityView) =>
  (items || []).reduce(
    (sum, item) => sum + convertQuantityByItem(item?.[quantityField], item?.[itemField], quantityView),
    0
  );

export const getQuantityAxisLabel = (baseLabel, quantityView) =>
  quantityView?.enabled
    ? `${baseLabel} (Supplier → Manufacturer raw materials converted to ${quantityView.productId})`
    : baseLabel;

export const getQuantityColumnLabel = (baseLabel, quantityView) =>
  quantityView?.enabled
    ? `${baseLabel} (${quantityView.productId} equivalent)`
    : baseLabel;

export const getDisplayItemLabel = (itemId, quantityView) =>
  isConvertibleRawMaterial(itemId, quantityView)
    ? `${itemId} (${quantityView.productId} equivalent)`
    : itemId;
