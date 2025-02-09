# Copyright 2021-2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file
# except in compliance with the License. A copy of the License is located at
#
# http://aws.amazon.com/asl/
#
# or in the "license" file accompanying this file. This file is distributed on an "AS IS"
# BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied. See the
# License for the specific language governing permissions and limitations under the License

BUILD_DIR:=.build
YAML_SRC:=encrypted_key.yaml
export ARMONIK_TAG
export ARMONIK_REGION?=eu-west-1

all: init

.PHONY: clean delete init

init: $(YAML_SRC)
	aws cloudformation create-stack --stack-name $(ARMONIK_TAG) --region $(ARMONIK_REGION) --template-body file://$(YAML_SRC) --parameters ParameterKey=BucketTag,ParameterValue=$(ARMONIK_TAG)
	@echo "Waiting for cloud formation successful deployment"
	@aws cloudformation wait stack-create-complete --stack-name $(ARMONIK_TAG) --region $(ARMONIK_REGION)
	aws cloudformation describe-stacks --stack-name $(ARMONIK_TAG) --region $(ARMONIK_REGION) --query 'Stacks[0]'

delete:
	aws cloudformation delete-stack --stack-name $(ARMONIK_TAG) --region $(ARMONIK_REGION)
	aws cloudformation wait stack-delete-complete --stack-name $(shell aws cloudformation describe-stacks --region $(ARMONIK_REGION) --stack-name $(ARMONIK_TAG) --query 'Stacks[0].StackId' --output text) --region $(ARMONIK_REGION)
	rm -rf .build

	
clean:
	rm -rf $(BUILD_DIR)/tag.*
	