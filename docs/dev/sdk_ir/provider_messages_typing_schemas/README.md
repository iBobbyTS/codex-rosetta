# Provider Messages Typing Schemas Analysis Plan

## Project Goal

Create a set of intermediate representations (IRs) for converting message formats among different LLM providers (OpenAI, Anthropic, and Google GenAI).

## Scope of Analysis

### Target Type Definitions

1. **OpenAI**: `ChatCompletionMessageParam`
2. **Anthropic**: `MessageParam`
3. **Google GenAI**: `ContentListUnionDict`

## Analysis Methodology

### Phase 1: Type Definition Extraction

For each provider, we will:

1. **Locate Source Files**

   - Find the installed package in the `l_t_c` conda environment
   - Locate the type definition files (usually `types.py` or `_types.py`)

2. **Extract the Complete Type Structure**

   - Primary type definitions
   - All related subtypes and Union types
   - TypedDict definitions
   - Literal types

3. **Record Key Information**
   - Field names and type annotations
   - Required vs optional fields (Required vs NotRequired)
   - Field docstrings and comments
   - Type constraints and validation rules

### Phase 2: Structured Documentation

Create a separate Markdown document for each provider containing:

1. **Type Hierarchy**

   - Mermaid diagrams showing type inheritance and composition relationships
   - Labels for every branch of each Union type

2. **Detailed Field Descriptions**

   - Tables listing all fields
   - Field types, required status, default values, and descriptions

3. **Code Examples**

   - Actual type definition code
   - Usage examples

4. **Special Considerations**
   - Features unique to each provider
   - Version differences
   - Known limitations

### Phase 3: Comparative Analysis

Create a comparison document that identifies:

1. **Shared Features**

   - Message types supported by all providers (such as text and image)
   - Common fields (such as role and content)
   - Similar structural patterns

2. **Differences**

   - Provider-specific message types (such as tool_use and function_call)
   - Differences in field names
   - Differences in structural organization
   - Differences in how types are expressed

3. **Conversion Challenges**
   - Features that cannot be mapped directly
   - Cases that require special handling
   - Risks of information loss

### Phase 4: IR Design

Design an intermediate representation based on the comparative analysis:

1. **Core Principles**

   - Preserve key information from every provider
   - Support bidirectional conversion
   - Ensure type safety
   - Remain easy to extend

2. **Design Considerations**

   - Whether to use TypedDict or dataclass
   - How to handle provider-specific features
   - Version compatibility strategy
   - Validation and error handling

3. **Conversion Strategy**
   - Mapping rules from IR → Provider
   - Parsing rules from Provider → IR
   - Edge-case handling
   - Fallback strategies (when the target provider does not support a feature)

## Document Structure

```
docs/dev/sdk_ir/provider_messages_typing_schemas/
├── README.md                    # This file: overall plan
├── openai.md                    # Detailed OpenAI type definitions
├── anthropic.md                 # Detailed Anthropic type definitions
├── google.md                    # Detailed Google GenAI type definitions
├── comparison.md                # Comparative analysis of all three providers
└── ir_design.md                 # Historical IR design document (not retained in this repository)
```

## Expected Deliverables

1. **Complete type definition documentation** (one document for each of the three providers)
2. **Comparative analysis report**
3. **IR design specification**
4. **Conversion strategy document**
5. **Implementation recommendations and best practices**

## Next Steps

Following the order of the todo list, start with OpenAI:

1. Locate the type definition files
2. Extract the complete structure
3. Create the documentation

Then process Anthropic and Google in sequence, followed by the comparative analysis and IR design.
