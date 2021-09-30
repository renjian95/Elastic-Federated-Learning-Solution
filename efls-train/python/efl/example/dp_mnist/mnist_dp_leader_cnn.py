# Copyright (C) 2016-2021 Alibaba Group Holding Limited
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import numpy as np
import tensorflow.compat.v1 as tf
import efl

train, test = tf.keras.datasets.mnist.load_data()
train_data, train_labels = train
test_data, test_labels = test

train_data = np.array(train_data, dtype=np.float32) / 255.0
test_data = np.array(test_data, dtype=np.float32) / 255.0

train_labels = np.array(train_labels, dtype=np.int32)
test_labels = np.array(test_labels, dtype=np.int32)

train_sample_id = np.ones(train_labels.shape)
test_sample_id = np.ones(test_labels.shape)

train_dataset = tf.data.Dataset.from_tensor_slices((train_data, train_labels, train_sample_id))
train_dataset = train_dataset.shuffle(1000).batch(256).repeat()
train_iterator = train_dataset.make_one_shot_iterator()

test_dataset = tf.data.Dataset.from_tensor_slices((test_data, test_labels, test_sample_id))
test_dataset = test_dataset.batch(100).repeat()
test_iterator = test_dataset.make_one_shot_iterator()

def input_fn(model, mode):
  if mode == efl.MODE.TRAIN:
    batch = train_iterator.get_next()
  else:
    batch = test_iterator.get_next()
  columns = {
      'img': [tf.feature_column.numeric_column('img', 28*28)],
      'label': [tf.feature_column.numeric_column('label', 1, dtype=tf.int32)],
      'sample_id': [tf.feature_column.numeric_column('sample_id', 1, dtype=tf.int32)]}
  features = {
      'img': batch[0],
      'label': batch[1],
      'sample_id': batch[2]}
  with tf.variable_scope('input_fn', reuse=tf.AUTO_REUSE):
    return efl.FederalSample(features, columns, model.federal_role,
                                 model.communicator, sample_id_name='sample_id',
                                 name='train' if mode == efl.MODE.TRAIN else 'eval')

def model_fn(model, sample, is_training):
  if is_training:
    labels = model.recv('labels_train', dtype=tf.int32, require_grad=False)
    y = model.recv('y_train', dtype=tf.float32, require_grad=True)
  else:
    labels = model.recv('labels_test', dtype=tf.int32, require_grad=False)
    y = model.recv('y_test', dtype=tf.float32, require_grad=False)
  y = tf.reshape(y, [-1, 512])
  y = tf.layers.dense(y, 32, activation='relu')
  logits = tf.layers.dense(y, 10)
  loss = tf.nn.sparse_softmax_cross_entropy_with_logits(labels=labels, logits=logits)
  if is_training:
    return loss
  else:
    prediction = tf.argmax(logits, axis=-1)
    accuracy = tf.metrics.accuracy(labels, prediction)
    model.add_metric('accuracy', accuracy, efl.MODE.EVAL)
    return accuracy[1]

def loss_fn(model, sample):
  with tf.variable_scope('fed_mnist'):
    return model_fn(model, sample, True)

def eval_fn(model, sample):
  with tf.variable_scope('fed_mnist', reuse=tf.AUTO_REUSE):
    return model_fn(model, sample, False)

CNN = efl.FederalModel()
CNN.input_fn(input_fn)
CNN.loss_fn(loss_fn)
CNN.eval_fn(eval_fn)
CNN.optimizer_fn(efl.optimizer_fn.optimizer_setter(efl.DPGradientDescentGaussianOptimizer(
    l2_norm_clip=1.0, noise_multiplier=1.0, learning_rate=0.25)))
CNN.compile(opt_config={'BACKEND_MODE': 'unnoise'})
CNN.fit(efl.procedure_fn.train_and_evaluate(train_step=235, eval_step=100, max_iter=20),
        log_step=100,
        project_name='fed_mnist')
