// Native-compatibility lint: code that renders on react-native-web but breaks or does nothing on a
// phone. The preview is a browser, so without this pass such code would look correct to the agent.
//
// Fatal (the render is replaced by the error panel): DOM host elements, onClick, string styles.
// Warnings (status "degraded"): platform branches, web-only styles, CSS shorthands, unit strings,
// shadow*/elevation (use boxShadow), className.
//
// Runs as a separate parse of the original source, so JSX and imports are seen before any
// transform rewrites them.

const WEB_ONLY_STYLE_KEYS = new Set([
  'cursor',
  'transition', 'transitionProperty', 'transitionDuration', 'transitionTimingFunction', 'transitionDelay',
  'animation', 'animationName', 'animationDuration', 'animationDelay', 'animationTimingFunction',
  'animationIterationCount', 'animationDirection', 'animationFillMode',
  'gridTemplateColumns', 'gridTemplateRows', 'gridTemplateAreas', 'gridColumn', 'gridRow', 'gridArea',
  'gridAutoFlow', 'gridAutoColumns', 'gridAutoRows', 'gridGap',
  'float', 'clear', 'whiteSpace', 'wordBreak', 'textOverflow', 'overflowWrap', 'hyphens',
  'listStyle', 'listStyleType', 'content', 'visibility', 'backdropFilter', 'clipPath', 'scrollBehavior',
  'willChange', 'objectPosition', 'backgroundImage', 'backgroundSize', 'backgroundPosition',
  'backgroundRepeat', 'backgroundAttachment',
]);

// CSS shorthands React Native doesn't accept (it has the longhands, e.g. borderWidth + borderColor).
const SHORTHAND_STYLE_KEYS = new Set([
  'border', 'borderTop', 'borderRight', 'borderBottom', 'borderLeft', 'background', 'font', 'flexFlow',
  'placeItems', 'placeContent', 'placeSelf', 'textDecoration',
]);

const LEGACY_SHADOW_KEYS = new Set(['shadowColor', 'shadowOffset', 'shadowOpacity', 'shadowRadius', 'elevation']);

// Keys whose values React Native wants as unitless numbers (or percentages / "auto").
const NUMERIC_STYLE_KEY = /^(fontSize|lineHeight|letterSpacing|(min|max)?(Width|Height)|width|height|(margin|padding)(Top|Right|Bottom|Left|Horizontal|Vertical|Start|End)?|top|right|bottom|left|border(Top|Right|Bottom|Left)?(Left|Right)?(Radius|Width)|borderRadius|borderWidth|gap|rowGap|columnGap|flexBasis)$/;
const UNIT_STRING = /^-?\d*\.?\d+\s*(px|em|rem|vh|vw|vmin|vmax|pt|dp)$/i;

const DISPLAY_VALUES = new Set(['flex', 'none', 'contents']);
const STYLE_PROPS = /^(style|contentContainerStyle|columnWrapperStyle|ListHeaderComponentStyle|ListFooterComponentStyle|imageStyle)$/;

function keyName(property) {
  if (property.type !== 'ObjectProperty' || property.computed) return null;
  if (property.key.type === 'Identifier') return property.key.name;
  if (property.key.type === 'StringLiteral') return property.key.value;
  return null;
}

export function lintNativeCompat(Babel, source, filename) {
  const findings = [];
  const seen = new Set();

  function add(rule, fatal, message, node) {
    const key = `${rule}|${message}`;
    if (seen.has(key)) return;
    seen.add(key);
    const start = node && node.loc && node.loc.start;
    findings.push({
      kind: 'native_compat',
      rule,
      fatal,
      message,
      line: start ? start.line : undefined,
      column: start ? start.column + 1 : undefined,
    });
  }

  function checkStyleObject(object) {
    for (const property of object.properties) {
      const name = keyName(property);
      if (!name) continue;
      const value = property.value;
      const text = value.type === 'StringLiteral' ? value.value : null;
      if (WEB_ONLY_STYLE_KEYS.has(name)) {
        add('web-style', false, `Style "${name}" is web-only and has no effect on a phone.`, property);
      } else if (SHORTHAND_STYLE_KEYS.has(name)) {
        add('css-shorthand', false, `"${name}" is a CSS shorthand React Native doesn't support; use the longhand styles (for example borderWidth and borderColor).`, property);
      } else if (LEGACY_SHADOW_KEYS.has(name)) {
        add('legacy-shadow', false, `"${name}" renders differently on iOS and Android; use boxShadow, e.g. boxShadow: '0px 4px 12px rgba(0, 0, 0, 0.12)'.`, property);
      } else if (name === 'display' && text !== null && !DISPLAY_VALUES.has(text)) {
        add('web-style', false, `display: '${text}' isn't supported on a phone; React Native lays out with flexbox.`, property);
      } else if (name === 'position' && (text === 'fixed' || text === 'sticky')) {
        add('web-style', false, `position: '${text}' isn't supported on a phone; use 'absolute' inside the screen.`, property);
      } else if (text !== null && NUMERIC_STYLE_KEY.test(name)) {
        if (UNIT_STRING.test(text.trim())) {
          add('unit-string', false, `${name}: '${text}' needs a unitless number on a phone, e.g. ${name}: ${parseFloat(text)}.`, property);
        } else if (/\s/.test(text.trim())) {
          add('css-shorthand', false, `${name}: '${text}' is a CSS shorthand; set each side separately (e.g. paddingVertical and paddingHorizontal).`, property);
        }
      }
    }
  }

  // Style expressions: objects, arrays of them, and conditional branches.
  function collectStyles(node) {
    if (!node) return;
    if (node.type === 'ObjectExpression') checkStyleObject(node);
    else if (node.type === 'ArrayExpression') node.elements.forEach(collectStyles);
    else if (node.type === 'ConditionalExpression') {
      collectStyles(node.consequent);
      collectStyles(node.alternate);
    } else if (node.type === 'LogicalExpression') {
      collectStyles(node.left);
      collectStyles(node.right);
    }
  }

  const plugin = () => ({
    visitor: {
      JSXOpeningElement(path) {
        const name = path.node.name;
        if (name.type === 'JSXIdentifier' && /^[a-z]/.test(name.name)) {
          add('host-element', true, `<${name.name}> is a web element; React Native has no DOM. Use View, Text, Image, Pressable or ScrollView.`, path.node);
        }
      },
      JSXAttribute(path) {
        const attribute = path.node;
        if (attribute.name.type !== 'JSXIdentifier') return;
        const name = attribute.name.name;
        if (name === 'onClick') {
          add('on-click', true, 'onClick does nothing on a phone; use Pressable with onPress.', attribute);
        } else if (name === 'className') {
          add('class-name', false, 'className has no effect in React Native (this stack uses StyleSheet); use style.', attribute);
        } else if (name === 'href') {
          add('web-prop', false, 'href is web-only; use Pressable with onPress for navigation.', attribute);
        } else if (STYLE_PROPS.test(name)) {
          // expo-status-bar's style prop is a string ("light" | "dark" | "auto"), not a style.
          const element = path.parent.name;
          if (element.type === 'JSXIdentifier' && element.name === 'StatusBar') return;
          if (attribute.value && attribute.value.type === 'StringLiteral') {
            add('style-string', true, `${name} must be a style object, not a CSS string.`, attribute);
          } else if (attribute.value && attribute.value.type === 'JSXExpressionContainer') {
            collectStyles(attribute.value.expression);
          }
        }
      },
      MemberExpression(path) {
        const { object, property } = path.node;
        if (object.type === 'Identifier' && object.name === 'Platform' && property.type === 'Identifier' && (property.name === 'OS' || property.name === 'select')) {
          add('platform-branch', false, `Platform.${property.name} is "web" in the preview, so a platform branch is never checked; write one layout for both platforms.`, path.node);
        }
      },
      CallExpression(path) {
        const callee = path.node.callee;
        const isCreate =
          callee.type === 'MemberExpression' &&
          callee.object.type === 'Identifier' &&
          callee.object.name === 'StyleSheet' &&
          callee.property.type === 'Identifier' &&
          callee.property.name === 'create';
        const argument = path.node.arguments[0];
        if (!isCreate || !argument || argument.type !== 'ObjectExpression') return;
        for (const property of argument.properties) {
          if (property.type === 'ObjectProperty' && property.value.type === 'ObjectExpression') checkStyleObject(property.value);
        }
      },
    },
  });

  Babel.transform(source, {
    filename,
    sourceType: 'module',
    code: false,
    ast: false,
    babelrc: false,
    configFile: false,
    parserOpts: { plugins: ['jsx'] },
    plugins: [plugin],
  });
  return findings;
}
